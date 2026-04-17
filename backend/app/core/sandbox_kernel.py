"""
Kernel-level security sandbox — Landlock filesystem restriction + capability detection.

Provides Linux Landlock LSM integration for fine-grained filesystem access control
on AI subprocesses. Degrades gracefully to a noop on non-Linux platforms or
kernels older than 5.13.

References:
- https://docs.kernel.org/userspace-api/landlock.html
- Backlog #11339: kernel-level security sandbox
"""
import ctypes
import ctypes.util
import logging
import os
import platform
import struct
from dataclasses import dataclass, field
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# ── Landlock ABI constants (kernel UAPI) ────────────────────────────────
LANDLOCK_CREATE_RULESET_VERSION = 0

# Access rights bitmask (Landlock ABI v1, kernel 5.13+)
LANDLOCK_ACCESS_FS_EXECUTE = 1 << 0
LANDLOCK_ACCESS_FS_WRITE_FILE = 1 << 1
LANDLOCK_ACCESS_FS_READ_FILE = 1 << 2
LANDLOCK_ACCESS_FS_READ_DIR = 1 << 3
LANDLOCK_ACCESS_FS_REMOVE_DIR = 1 << 4
LANDLOCK_ACCESS_FS_REMOVE_FILE = 1 << 5
LANDLOCK_ACCESS_FS_MAKE_CHAR = 1 << 6
LANDLOCK_ACCESS_FS_MAKE_DIR = 1 << 7
LANDLOCK_ACCESS_FS_MAKE_REG = 1 << 8
LANDLOCK_ACCESS_FS_MAKE_SOCK = 1 << 9
LANDLOCK_ACCESS_FS_MAKE_FIFO = 1 << 10
LANDLOCK_ACCESS_FS_MAKE_BLOCK = 1 << 11
LANDLOCK_ACCESS_FS_MAKE_SYM = 1 << 12

# Composite masks for convenience
LANDLOCK_ACCESS_FS_READ = (
    LANDLOCK_ACCESS_FS_EXECUTE
    | LANDLOCK_ACCESS_FS_READ_FILE
    | LANDLOCK_ACCESS_FS_READ_DIR
)
LANDLOCK_ACCESS_FS_WRITE = (
    LANDLOCK_ACCESS_FS_WRITE_FILE
    | LANDLOCK_ACCESS_FS_REMOVE_DIR
    | LANDLOCK_ACCESS_FS_REMOVE_FILE
    | LANDLOCK_ACCESS_FS_MAKE_CHAR
    | LANDLOCK_ACCESS_FS_MAKE_DIR
    | LANDLOCK_ACCESS_FS_MAKE_REG
    | LANDLOCK_ACCESS_FS_MAKE_SOCK
    | LANDLOCK_ACCESS_FS_MAKE_FIFO
    | LANDLOCK_ACCESS_FS_MAKE_BLOCK
    | LANDLOCK_ACCESS_FS_MAKE_SYM
)
LANDLOCK_ACCESS_FS_READWRITE = LANDLOCK_ACCESS_FS_READ | LANDLOCK_ACCESS_FS_WRITE

# Syscall numbers (x86_64)
_SYS_LANDLOCK_CREATE_RULESET = 444
_SYS_LANDLOCK_ADD_RULE = 445
_SYS_LANDLOCK_RESTRICT_SELF = 446

# Rule type
LANDLOCK_RULE_PATH_BENEATH = 1

# prctl constants for no_new_privs
_PR_SET_NO_NEW_PRIVS = 38

# Minimum kernel version for Landlock support
_MIN_KERNEL_MAJOR = 5
_MIN_KERNEL_MINOR = 13


def _parse_kernel_version(release: str) -> tuple[int, int]:
    """Extract (major, minor) from a kernel release string like '5.15.0-91-generic'."""
    try:
        parts = release.split(".")
        return int(parts[0]), int(parts[1])
    except (IndexError, ValueError):
        return (0, 0)


def _check_proc_flag(path: str) -> bool:
    """Check if a /proc flag file exists and contains a truthy value."""
    try:
        with open(path, "r") as f:
            val = f.read().strip()
            return val not in ("", "0")
    except (OSError, IOError):
        return False


def detect_kernel_capabilities() -> dict:
    """Detect available kernel security features.

    Returns a dict with boolean flags:
    - landlock: True if Landlock LSM is available (Linux >= 5.13)
    - seccomp: True if seccomp-bpf is available
    - netns: True if network namespaces are available (user namespaces enabled)
    - kernel_version: tuple (major, minor) or (0, 0) on non-Linux
    """
    result = {
        "landlock": False,
        "seccomp": False,
        "netns": False,
        "kernel_version": (0, 0),
    }

    if platform.system() != "Linux":
        return result

    try:
        release = os.uname().release
    except AttributeError:
        return result

    major, minor = _parse_kernel_version(release)
    result["kernel_version"] = (major, minor)

    # Landlock: kernel >= 5.13 and LSM enabled
    if (major, minor) >= (_MIN_KERNEL_MAJOR, _MIN_KERNEL_MINOR):
        # Check if Landlock is actually enabled in the running kernel
        if os.path.exists("/sys/kernel/security/landlock/status"):
            result["landlock"] = True
        else:
            # Fallback: try the syscall with version query — returns ABI version or -1
            result["landlock"] = _probe_landlock_syscall()

    # seccomp: check /proc/sys/kernel/seccomp/actions_avail or boot config
    result["seccomp"] = (
        os.path.exists("/proc/sys/kernel/seccomp/actions_avail")
        or _check_proc_flag("/proc/sys/kernel/seccomp/actions_logged")
    )

    # netns: user namespaces enabled
    result["netns"] = _check_proc_flag("/proc/sys/kernel/unprivileged_userns_clone")

    return result


def _probe_landlock_syscall() -> bool:
    """Probe Landlock availability by calling create_ruleset with version flag."""
    try:
        libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
        ret = libc.syscall(
            ctypes.c_long(_SYS_LANDLOCK_CREATE_RULESET),
            ctypes.c_void_p(None),
            ctypes.c_size_t(0),
            ctypes.c_uint32(LANDLOCK_CREATE_RULESET_VERSION),
        )
        if ret >= 0:
            os.close(ret)  # close the fd returned on success
            return True
        return False
    except (OSError, TypeError):
        return False


@dataclass
class LandlockSandbox:
    """Landlock filesystem sandbox for restricting subprocess file access.

    Usage:
        sandbox = LandlockSandbox()
        sandbox.restrict_paths(
            allowed_read=["/usr", "/lib", "/proc"],
            allowed_rw=["/tmp/workspace"],
        )
        preexec = sandbox.apply_to_preexec()
        subprocess.Popen(cmd, preexec_fn=preexec)
    """

    allowed_read: list[str] = field(default_factory=list)
    allowed_rw: list[str] = field(default_factory=list)
    _available: bool = field(init=False, default=False)

    def __post_init__(self):
        caps = detect_kernel_capabilities()
        self._available = caps["landlock"]

    @property
    def available(self) -> bool:
        return self._available

    def restrict_paths(
        self,
        allowed_read: Optional[list[str]] = None,
        allowed_rw: Optional[list[str]] = None,
    ) -> "LandlockSandbox":
        """Configure filesystem access restrictions.

        Parameters
        ----------
        allowed_read : list[str], optional
            Paths with read-only access.
        allowed_rw : list[str], optional
            Paths with read-write access.

        Returns
        -------
        self for chaining.
        """
        if allowed_read is not None:
            self.allowed_read = list(allowed_read)
        if allowed_rw is not None:
            self.allowed_rw = list(allowed_rw)
        return self

    def apply_to_preexec(
        self, existing_preexec: Optional[Callable] = None
    ) -> Optional[Callable]:
        """Return a preexec_fn that applies Landlock restrictions.

        If Landlock is not available, returns existing_preexec unchanged (noop).
        If existing_preexec is provided, chains both functions.

        Parameters
        ----------
        existing_preexec : callable, optional
            An existing preexec_fn to chain with Landlock setup.

        Returns
        -------
        callable or None
        """
        if not self._available:
            logger.debug("[Landlock] Not available, returning existing preexec_fn")
            return existing_preexec

        if not self.allowed_read and not self.allowed_rw:
            logger.debug("[Landlock] No paths configured, returning existing preexec_fn")
            return existing_preexec

        # Capture snapshot of paths for the closure
        read_paths = list(self.allowed_read)
        rw_paths = list(self.allowed_rw)

        def _preexec():
            # Run existing preexec first (e.g., setuid)
            if existing_preexec is not None:
                existing_preexec()
            _apply_landlock(read_paths, rw_paths)

        return _preexec


def _apply_landlock(read_paths: list[str], rw_paths: list[str]) -> None:
    """Apply Landlock restrictions in the current process (called inside preexec_fn).

    This function is executed in the child process after fork(), before exec().
    """
    try:
        libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
    except (OSError, TypeError) as e:
        logger.warning(f"[Landlock] Cannot load libc: {e}")
        return

    handled_access = LANDLOCK_ACCESS_FS_READWRITE

    # ── Step 1: Create ruleset ──
    # struct landlock_ruleset_attr { __u64 handled_access_fs; }
    ruleset_attr = struct.pack("Q", handled_access)
    ruleset_fd = libc.syscall(
        ctypes.c_long(_SYS_LANDLOCK_CREATE_RULESET),
        ctypes.c_char_p(ruleset_attr),
        ctypes.c_size_t(len(ruleset_attr)),
        ctypes.c_uint32(0),
    )
    if ruleset_fd < 0:
        errno = ctypes.get_errno()
        logger.warning(f"[Landlock] create_ruleset failed, errno={errno}")
        return

    try:
        # ── Step 2: Add rules for each path ──
        for path in read_paths:
            _add_path_rule(libc, ruleset_fd, path, LANDLOCK_ACCESS_FS_READ)

        for path in rw_paths:
            _add_path_rule(libc, ruleset_fd, path, LANDLOCK_ACCESS_FS_READWRITE)

        # ── Step 3: Set no_new_privs (required before restrict_self) ──
        libc.prctl(
            ctypes.c_int(_PR_SET_NO_NEW_PRIVS),
            ctypes.c_ulong(1),
            ctypes.c_ulong(0),
            ctypes.c_ulong(0),
            ctypes.c_ulong(0),
        )

        # ── Step 4: Enforce the ruleset ──
        ret = libc.syscall(
            ctypes.c_long(_SYS_LANDLOCK_RESTRICT_SELF),
            ctypes.c_int(ruleset_fd),
            ctypes.c_uint32(0),
        )
        if ret < 0:
            errno = ctypes.get_errno()
            logger.warning(f"[Landlock] restrict_self failed, errno={errno}")
        else:
            logger.info("[Landlock] Filesystem restrictions applied successfully")

    finally:
        os.close(ruleset_fd)


def _add_path_rule(
    libc: ctypes.CDLL, ruleset_fd: int, path: str, access_mask: int
) -> None:
    """Add a Landlock path-beneath rule for the given path."""
    try:
        path_fd = os.open(path, os.O_PATH | os.O_CLOEXEC)
    except (OSError, AttributeError) as e:
        logger.debug(f"[Landlock] Cannot open path {path}: {e}")
        return

    try:
        # struct landlock_path_beneath_attr {
        #     __u64 allowed_access;
        #     __s32 parent_fd;
        # } — packed as Q (u64) + i (s32)
        path_beneath_attr = struct.pack("Qi", access_mask, path_fd)

        ret = libc.syscall(
            ctypes.c_long(_SYS_LANDLOCK_ADD_RULE),
            ctypes.c_int(ruleset_fd),
            ctypes.c_int(LANDLOCK_RULE_PATH_BENEATH),
            ctypes.c_char_p(path_beneath_attr),
            ctypes.c_uint32(0),
        )
        if ret < 0:
            errno = ctypes.get_errno()
            logger.debug(
                f"[Landlock] add_rule failed for {path}, errno={errno}"
            )
    finally:
        os.close(path_fd)
