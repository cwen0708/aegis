#!/usr/bin/env python3
"""
Aegis Heartbeat L1 — 哨兵（每 5 分鐘）

純 Python，零 AI 依賴。快速檢查系統健康並自動修復已知問題。
由 systemd timer 觸發，不依賴 Aegis 排程。

用法：
  python3 heartbeat.py              # 正常執行
  python3 heartbeat.py --dry-run    # 只檢查不修復
  python3 heartbeat.py --verbose    # 詳細輸出
"""
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ============================================================
# 設定
# ============================================================

SCRIPT_DIR = Path(__file__).parent
CONFIG_PATH = SCRIPT_DIR / "config.json"
LOCK_FILE = Path("/tmp/aegis-heartbeat.lock")
LOCK_TTL = 300  # 5 分鐘

# 從 config.json 載入設定，支援未配置時的預設值
def _load_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}

_CFG = _load_config()
API_BASE = _CFG.get("aegis_api", "http://127.0.0.1:8899/api/v1")
SERVICES = _CFG.get("services", ["aegis", "aegis-worker"])
ZOMBIE_THRESHOLD = _CFG.get("zombie_threshold_minutes", 60) * 60  # 轉為秒

# 自動偵測路徑
_HOME = Path.home()
VENV_PYTHON = Path(_CFG.get("venv_path", "")) or _HOME / ".local/aegis/backend/venv/bin/python"
BACKEND_DIR = VENV_PYTHON.parent.parent if str(VENV_PYTHON) != "." else _HOME / ".local/aegis/backend"
RESTART_COOLDOWN = _CFG.get("restart_cooldown_minutes", 10) * 60

DRY_RUN = "--dry-run" in sys.argv
VERBOSE = "--verbose" in sys.argv


# ============================================================
# 工具函數
# ============================================================

def log(msg: str, level: str = "INFO") -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"{ts} [{level}] {msg}")


def run_cmd(cmd: list[str], timeout: int = 10) -> tuple[int, str]:
    """執行指令，回傳 (exit_code, stdout)"""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip()
    except subprocess.TimeoutExpired:
        return -1, "timeout"
    except Exception as e:
        return -1, str(e)


def api_get(path: str) -> dict | None:
    """GET API，失敗回 None"""
    try:
        resp = urllib.request.urlopen(f"{API_BASE}{path}", timeout=5)
        return json.loads(resp.read())
    except Exception:
        return None


def api_post(path: str) -> bool:
    """POST API，回傳是否成功"""
    try:
        req = urllib.request.Request(f"{API_BASE}{path}", method="POST")
        urllib.request.urlopen(req, timeout=5)
        return True
    except Exception:
        return False


def restart_service(name: str) -> bool:
    """重啟 systemd 服務"""
    if DRY_RUN:
        log(f"[DRY-RUN] Would restart {name}", "WARN")
        return True
    code, _ = run_cmd(["sudo", "systemctl", "restart", name], timeout=15)
    return code == 0


def _cooldown_key(service: str) -> Path:
    return Path(f"/tmp/aegis-heartbeat-restart-{service}")


def _check_cooldown(service: str) -> bool:
    """回傳 True 表示還在冷卻期，不應重啟"""
    f = _cooldown_key(service)
    if f.exists():
        age = time.time() - f.stat().st_mtime
        if age < RESTART_COOLDOWN:
            return True
    return False


def _set_cooldown(service: str) -> None:
    _cooldown_key(service).write_text(str(int(time.time())))


# ============================================================
# 檢查項目
# ============================================================

class CheckResult:
    def __init__(self):
        self.ok = True
        self.fixes: list[str] = []
        self.warnings: list[str] = []
        self.stats: dict = {}

    def fail(self, fix: str) -> None:
        self.ok = False
        self.fixes.append(fix)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)


def check_services(result: CheckResult) -> None:
    """1. 檢查 systemd 服務是否 active"""
    for svc in SERVICES:
        code, output = run_cmd(["systemctl", "is-active", svc])
        if output != "active":
            log(f"{svc} is {output}", "WARN")
            if _check_cooldown(svc):
                result.warn(f"{svc} down but in cooldown")
                continue
            if restart_service(svc):
                _set_cooldown(svc)
                result.fail(f"restarted {svc}")
                log(f"Restarted {svc}", "FIX")
            else:
                result.warn(f"failed to restart {svc}")
        elif VERBOSE:
            log(f"{svc}: active")


def check_api(result: CheckResult) -> None:
    """2. 檢查 API 是否回應"""
    status = api_get("/runner/status")
    if status is None:
        log("API not responding", "WARN")
        if not _check_cooldown("aegis"):
            if restart_service("aegis"):
                _set_cooldown("aegis")
                result.fail("restarted aegis (API down)")
                time.sleep(3)
            else:
                result.warn("API down, restart failed")
        return

    used = status.get("workstations_used", 0)
    total = status.get("workstations_total", 3)
    tasks = status.get("running_tasks", [])
    result.stats["workers"] = f"{used}/{total}"
    result.stats["version"] = status.get("version", "?")

    if VERBOSE:
        log(f"API OK: workers {used}/{total}, {len(tasks)} tasks")


def check_zombies(result: CheckResult) -> None:
    """3. 清理殭屍任務（執行超過閾值）"""
    status = api_get("/runner/status")
    if not status:
        return

    now = time.time()
    zombies_killed = []

    for task in status.get("running_tasks", []):
        started = task.get("started_at", now)
        elapsed = now - started
        task_id = task.get("task_id")

        if elapsed > ZOMBIE_THRESHOLD:
            elapsed_min = int(elapsed / 60)
            log(f"Zombie: #{task_id} running {elapsed_min}m", "WARN")
            if not DRY_RUN and api_post(f"/cards/{task_id}/abort"):
                zombies_killed.append(f"#{task_id}({elapsed_min}m)")
                log(f"Aborted #{task_id}", "FIX")

    if zombies_killed:
        result.fail(f"aborted {', '.join(zombies_killed)}")

    result.stats["zombies_killed"] = len(zombies_killed)


def check_venv(result: CheckResult) -> None:
    """4. 檢查 venv 完整性"""
    if VENV_PYTHON.exists():
        if VERBOSE:
            log("venv: OK")
        return

    log("venv/bin/python missing!", "WARN")
    if DRY_RUN:
        result.warn("venv missing (dry-run)")
        return

    venv_dir = VENV_PYTHON.parent.parent
    code, _ = run_cmd(["python3", "-m", "venv", str(venv_dir)], timeout=30)
    if code != 0:
        result.warn("venv rebuild failed")
        return

    req_file = BACKEND_DIR / "requirements.txt"
    if req_file.exists():
        code, _ = run_cmd(
            [str(VENV_PYTHON), "-m", "pip", "install", "-r", str(req_file), "-q"],
            timeout=120,
        )

    if VENV_PYTHON.exists():
        result.fail("rebuilt venv")
        # 重啟服務
        for svc in SERVICES:
            restart_service(svc)
            _set_cooldown(svc)
        log("venv rebuilt + services restarted", "FIX")
    else:
        result.warn("venv rebuild incomplete")


def check_error_logs(result: CheckResult) -> None:
    """5. 檢查 worker 近期錯誤"""
    code, output = run_cmd([
        "journalctl", "-u", "aegis-worker",
        "--since", "5 min ago", "--no-pager",
        "-p", "err",
    ], timeout=10)

    error_count = len(output.strip().split("\n")) if output.strip() else 0
    result.stats["recent_errors"] = error_count

    if error_count > 20:
        log(f"Worker has {error_count} errors in 5min", "WARN")
        if not _check_cooldown("aegis-worker"):
            if restart_service("aegis-worker"):
                _set_cooldown("aegis-worker")
                result.fail(f"restarted worker ({error_count} errors)")


# ============================================================
# 主程式
# ============================================================

def acquire_lock() -> bool:
    """簡易 file lock，防止多實例同時跑"""
    if LOCK_FILE.exists():
        age = time.time() - LOCK_FILE.stat().st_mtime
        if age < LOCK_TTL:
            return False
    LOCK_FILE.write_text(str(os.getpid()))
    return True


def release_lock() -> None:
    LOCK_FILE.unlink(missing_ok=True)


def main() -> int:
    if not acquire_lock():
        log("Another heartbeat is running, skip", "WARN")
        return 0

    try:
        result = CheckResult()

        check_services(result)
        check_api(result)
        check_zombies(result)
        check_venv(result)
        check_error_logs(result)

        # 產出一行摘要
        workers = result.stats.get("workers", "?/?")
        zk = result.stats.get("zombies_killed", 0)
        errs = result.stats.get("recent_errors", 0)

        if result.ok and not result.warnings:
            summary = f"✓ L1 OK | workers: {workers} | errors: {errs}"
        elif result.fixes:
            fixes = ", ".join(result.fixes)
            summary = f"⚠ L1 FIXED | {fixes} | workers: {workers}"
        else:
            warns = ", ".join(result.warnings)
            summary = f"✗ L1 WARN | {warns} | workers: {workers}"

        log(summary)
        return 0 if result.ok else 1

    finally:
        release_lock()


if __name__ == "__main__":
    sys.exit(main())
