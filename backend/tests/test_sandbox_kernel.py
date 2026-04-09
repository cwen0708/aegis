"""
Tests for sandbox_kernel.py — Landlock filesystem sandbox + capability detection.

These tests are designed to run on any platform (Windows/macOS/Linux) by mocking
the Linux-specific calls.
"""
import os
import platform
from unittest.mock import MagicMock, patch, mock_open

import pytest

from app.core.sandbox_kernel import (
    LandlockSandbox,
    detect_kernel_capabilities,
    _parse_kernel_version,
    LANDLOCK_ACCESS_FS_READ,
    LANDLOCK_ACCESS_FS_READWRITE,
)


# ── _parse_kernel_version ────────────────────────────────────────────────

class TestParseKernelVersion:
    def test_standard_release(self):
        assert _parse_kernel_version("5.15.0-91-generic") == (5, 15)

    def test_minimal_release(self):
        assert _parse_kernel_version("6.1.0") == (6, 1)

    def test_old_kernel(self):
        assert _parse_kernel_version("4.19.128") == (4, 19)

    def test_malformed_release(self):
        assert _parse_kernel_version("not-a-kernel") == (0, 0)

    def test_empty_string(self):
        assert _parse_kernel_version("") == (0, 0)

    def test_single_number(self):
        assert _parse_kernel_version("5") == (0, 0)


# ── detect_kernel_capabilities ───────────────────────────────────────────

class TestDetectKernelCapabilities:
    @patch("app.core.sandbox_kernel.platform.system", return_value="Windows")
    def test_noop_on_windows(self, _mock_sys):
        caps = detect_kernel_capabilities()
        assert caps["landlock"] is False
        assert caps["seccomp"] is False
        assert caps["netns"] is False
        assert caps["kernel_version"] == (0, 0)

    @patch("app.core.sandbox_kernel.platform.system", return_value="Darwin")
    def test_noop_on_macos(self, _mock_sys):
        caps = detect_kernel_capabilities()
        assert caps["landlock"] is False
        assert caps["seccomp"] is False

    @patch("app.core.sandbox_kernel.os.path.exists", return_value=False)
    @patch("app.core.sandbox_kernel._check_proc_flag", return_value=False)
    @patch("app.core.sandbox_kernel._probe_landlock_syscall", return_value=False)
    @patch("app.core.sandbox_kernel.os.uname", create=True)
    @patch("app.core.sandbox_kernel.platform.system", return_value="Linux")
    def test_old_linux_kernel(self, _sys, mock_uname, _probe, _proc, _exists):
        mock_uname.return_value = MagicMock(release="4.19.128-generic")
        caps = detect_kernel_capabilities()
        assert caps["landlock"] is False
        assert caps["kernel_version"] == (4, 19)

    @patch("app.core.sandbox_kernel._check_proc_flag", return_value=False)
    @patch("app.core.sandbox_kernel.os.path.exists")
    @patch("app.core.sandbox_kernel.os.uname", create=True)
    @patch("app.core.sandbox_kernel.platform.system", return_value="Linux")
    def test_linux_5_15_with_landlock_sysfs(self, _sys, mock_uname, mock_exists, _proc):
        mock_uname.return_value = MagicMock(release="5.15.0-91-generic")
        mock_exists.side_effect = lambda p: p == "/sys/kernel/security/landlock/status"
        caps = detect_kernel_capabilities()
        assert caps["landlock"] is True
        assert caps["kernel_version"] == (5, 15)

    @patch("app.core.sandbox_kernel._check_proc_flag", return_value=False)
    @patch("app.core.sandbox_kernel._probe_landlock_syscall", return_value=True)
    @patch("app.core.sandbox_kernel.os.path.exists", return_value=False)
    @patch("app.core.sandbox_kernel.os.uname", create=True)
    @patch("app.core.sandbox_kernel.platform.system", return_value="Linux")
    def test_linux_landlock_probe_fallback(self, _sys, mock_uname, _exists, _probe, _proc):
        mock_uname.return_value = MagicMock(release="5.13.0")
        caps = detect_kernel_capabilities()
        assert caps["landlock"] is True

    @patch("app.core.sandbox_kernel._check_proc_flag", return_value=False)
    @patch("app.core.sandbox_kernel.os.path.exists")
    @patch("app.core.sandbox_kernel.os.uname", create=True)
    @patch("app.core.sandbox_kernel.platform.system", return_value="Linux")
    def test_seccomp_detected(self, _sys, mock_uname, mock_exists, _proc):
        mock_uname.return_value = MagicMock(release="5.15.0")
        mock_exists.side_effect = lambda p: p == "/proc/sys/kernel/seccomp/actions_avail"
        caps = detect_kernel_capabilities()
        assert caps["seccomp"] is True

    @patch("app.core.sandbox_kernel.os.path.exists", return_value=False)
    @patch("app.core.sandbox_kernel._check_proc_flag")
    @patch("app.core.sandbox_kernel.os.uname", create=True)
    @patch("app.core.sandbox_kernel.platform.system", return_value="Linux")
    def test_netns_detected(self, _sys, mock_uname, mock_proc, _exists):
        mock_uname.return_value = MagicMock(release="5.15.0")
        mock_proc.side_effect = (
            lambda p: p == "/proc/sys/kernel/unprivileged_userns_clone"
        )
        caps = detect_kernel_capabilities()
        assert caps["netns"] is True


# ── LandlockSandbox ─────────────────────────────────────────────────────

class TestLandlockSandbox:
    @patch(
        "app.core.sandbox_kernel.detect_kernel_capabilities",
        return_value={"landlock": False, "seccomp": False, "netns": False, "kernel_version": (0, 0)},
    )
    def test_noop_on_unsupported_platform(self, _caps):
        sandbox = LandlockSandbox()
        assert sandbox.available is False
        sandbox.restrict_paths(allowed_read=["/usr"], allowed_rw=["/tmp"])
        preexec = sandbox.apply_to_preexec()
        assert preexec is None

    @patch(
        "app.core.sandbox_kernel.detect_kernel_capabilities",
        return_value={"landlock": False, "seccomp": False, "netns": False, "kernel_version": (0, 0)},
    )
    def test_noop_chains_existing_preexec(self, _caps):
        """When Landlock unavailable, existing preexec_fn is returned as-is."""
        existing = MagicMock()
        sandbox = LandlockSandbox()
        preexec = sandbox.apply_to_preexec(existing_preexec=existing)
        assert preexec is existing

    @patch(
        "app.core.sandbox_kernel.detect_kernel_capabilities",
        return_value={"landlock": True, "seccomp": False, "netns": False, "kernel_version": (5, 15)},
    )
    def test_returns_preexec_when_available(self, _caps):
        sandbox = LandlockSandbox()
        assert sandbox.available is True
        sandbox.restrict_paths(allowed_read=["/usr"], allowed_rw=["/tmp/work"])
        preexec = sandbox.apply_to_preexec()
        assert callable(preexec)

    @patch(
        "app.core.sandbox_kernel.detect_kernel_capabilities",
        return_value={"landlock": True, "seccomp": False, "netns": False, "kernel_version": (5, 15)},
    )
    def test_no_paths_returns_none(self, _caps):
        """When available but no paths configured, no preexec is generated."""
        sandbox = LandlockSandbox()
        preexec = sandbox.apply_to_preexec()
        assert preexec is None

    @patch(
        "app.core.sandbox_kernel.detect_kernel_capabilities",
        return_value={"landlock": True, "seccomp": False, "netns": False, "kernel_version": (5, 15)},
    )
    def test_chains_existing_preexec(self, _caps):
        """When Landlock available, existing preexec_fn is chained."""
        existing = MagicMock()
        sandbox = LandlockSandbox()
        sandbox.restrict_paths(allowed_read=["/usr"])
        preexec = sandbox.apply_to_preexec(existing_preexec=existing)
        assert callable(preexec)
        assert preexec is not existing  # should be a new wrapper

    @patch(
        "app.core.sandbox_kernel.detect_kernel_capabilities",
        return_value={"landlock": True, "seccomp": False, "netns": False, "kernel_version": (5, 15)},
    )
    def test_restrict_paths_is_chainable(self, _caps):
        sandbox = LandlockSandbox()
        result = sandbox.restrict_paths(allowed_read=["/usr"])
        assert result is sandbox

    @patch(
        "app.core.sandbox_kernel.detect_kernel_capabilities",
        return_value={"landlock": True, "seccomp": False, "netns": False, "kernel_version": (5, 15)},
    )
    def test_restrict_paths_captures_snapshot(self, _caps):
        """Paths are captured at apply time, later mutations don't affect preexec."""
        sandbox = LandlockSandbox()
        read_list = ["/usr"]
        sandbox.restrict_paths(allowed_read=read_list)
        preexec = sandbox.apply_to_preexec()
        # Mutate original list after apply
        read_list.append("/var")
        # sandbox's internal list should be independent
        assert "/var" not in sandbox.allowed_read


# ── Integration with sandbox.py get_popen_kwargs ─────────────────────────

class TestGetPopenKwargsLandlock:
    @patch("app.core.sandbox.platform.system", return_value="Windows")
    def test_windows_ignores_landlock(self, _sys):
        from app.core.sandbox import get_popen_kwargs

        kwargs = get_popen_kwargs(landlock_paths={"allowed_read": ["/usr"]})
        assert "preexec_fn" not in kwargs

    @patch("app.core.sandbox.platform.system", return_value="Linux")
    def test_linux_no_landlock_paths(self, _sys):
        """Default call (no landlock_paths) should not import sandbox_kernel."""
        from app.core.sandbox import get_popen_kwargs

        # Should not raise, should not have landlock-related changes
        with patch("app.core.sandbox.logger") as mock_logger:
            kwargs = get_popen_kwargs()
            # No landlock log messages expected
            landlock_calls = [
                c for c in mock_logger.info.call_args_list
                if "Landlock" in str(c)
            ]
            assert len(landlock_calls) == 0

    @patch("app.core.sandbox.platform.system", return_value="Linux")
    def test_linux_with_landlock_available(self, _sys):
        from app.core.sandbox import get_popen_kwargs

        mock_sandbox_instance = MagicMock()
        mock_sandbox_instance.apply_to_preexec.return_value = lambda: None

        with patch("app.core.sandbox_kernel.LandlockSandbox", return_value=mock_sandbox_instance):
            kwargs = get_popen_kwargs(
                landlock_paths={"allowed_read": ["/usr"], "allowed_rw": ["/tmp"]}
            )
            assert "preexec_fn" in kwargs
            mock_sandbox_instance.restrict_paths.assert_called_once_with(
                allowed_read=["/usr"],
                allowed_rw=["/tmp"],
            )

    @patch("app.core.sandbox.platform.system", return_value="Linux")
    def test_linux_landlock_failure_graceful(self, _sys):
        """If Landlock setup raises, get_popen_kwargs should not crash."""
        from app.core.sandbox import get_popen_kwargs

        with patch(
            "app.core.sandbox_kernel.LandlockSandbox",
            side_effect=RuntimeError("test error"),
        ):
            kwargs = get_popen_kwargs(
                landlock_paths={"allowed_read": ["/usr"]}
            )
            # Should still return valid kwargs, just without Landlock
            assert "start_new_session" in kwargs

    def test_backward_compat_no_args(self):
        """get_popen_kwargs() with no args should work exactly as before."""
        from app.core.sandbox import get_popen_kwargs

        kwargs = get_popen_kwargs()
        # Should return without error on any platform
        assert isinstance(kwargs, dict)


# ── Import safety ────────────────────────────────────────────────────────

class TestImportSafety:
    def test_import_on_any_platform(self):
        """sandbox_kernel should import without error on any platform."""
        import app.core.sandbox_kernel as sk
        assert hasattr(sk, "detect_kernel_capabilities")
        assert hasattr(sk, "LandlockSandbox")

    def test_detect_capabilities_on_current_platform(self):
        """detect_kernel_capabilities should return a well-formed dict on any OS."""
        caps = detect_kernel_capabilities()
        assert "landlock" in caps
        assert "seccomp" in caps
        assert "netns" in caps
        assert "kernel_version" in caps
        assert isinstance(caps["kernel_version"], tuple)
        assert len(caps["kernel_version"]) == 2
