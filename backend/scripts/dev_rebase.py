#!/usr/bin/env python3
"""
Aegis Dev Worktree Rebase Script
獨立執行的 dev 分支同步腳本，與主更新流程分離。

職責：
- 將 /home/cwen0708/projects/Aegis-dev worktree（dev 分支）rebase onto origin/main
- 一天只跑一次（由 CronJob 觸發）
- 與 hot_update 獨立，dev rebase 失敗不影響 main 部署

Lockfile: backend/.dev_rebase.lock（24 小時 TTL）
單日鎖 SystemSetting: dev_rebase_last_run_date（台北時區 YYYY-MM-DD）
"""
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

SCRIPT_DIR = Path(__file__).parent
BACKEND_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = BACKEND_DIR.parent

# Dev worktree 位置（GCP aegis-gs 上的實際路徑）
DEV_WORKTREE = Path("/home/cwen0708/projects/Aegis-dev")

# Lockfile（24 小時 TTL，防止意外重疊執行）
LOCK_FILE = BACKEND_DIR / ".dev_rebase.lock"
LOCK_TTL_SECONDS = 24 * 3600

# 單日鎖（防止同日重複觸發）
LAST_RUN_KEY = "dev_rebase_last_run_date"
LOCK_TZ = "Asia/Taipei"

# 加入 backend 到 path，讓 app.database 可用
sys.path.insert(0, str(BACKEND_DIR))


def _today_taipei() -> str:
    return datetime.now(ZoneInfo(LOCK_TZ)).strftime("%Y-%m-%d")


def _check_lockfile() -> bool:
    """檢查 lockfile 是否在 TTL 內，回傳 True 表示可執行。"""
    try:
        if LOCK_FILE.exists():
            age = time.time() - LOCK_FILE.stat().st_mtime
            if age < LOCK_TTL_SECONDS:
                print(f"[DevRebase] Lockfile 存在（{int(age)}s 前），跳過")
                return False
        LOCK_FILE.write_text(str(int(time.time())), encoding="utf-8")
        return True
    except OSError as exc:
        print(f"[DevRebase] Lockfile 處理失敗（繼續執行）: {exc}")
        return True


def _release_lockfile() -> None:
    try:
        LOCK_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def _get_last_run_date() -> str:
    try:
        from app.database import engine
        from app.models.core import SystemSetting
        from sqlmodel import Session
        with Session(engine) as session:
            setting = session.get(SystemSetting, LAST_RUN_KEY)
            return setting.value if setting and setting.value else ""
    except Exception as exc:
        print(f"[DevRebase] 讀取單日鎖失敗（視為未執行）: {exc}")
        return ""


def _mark_last_run_date(date_str: str) -> None:
    try:
        from app.database import engine
        from app.models.core import SystemSetting
        from sqlmodel import Session
        with Session(engine) as session:
            setting = session.get(SystemSetting, LAST_RUN_KEY)
            if setting:
                setting.value = date_str
            else:
                setting = SystemSetting(key=LAST_RUN_KEY, value=date_str)
            session.add(setting)
            session.commit()
    except Exception as exc:
        print(f"[DevRebase] 寫入單日鎖失敗: {exc}")


def _run(cmd: list, cwd: Path) -> tuple[int, str, str]:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout, proc.stderr


def main() -> int:
    """回傳值：0=成功/已跳過，1=失敗"""
    if not DEV_WORKTREE.exists():
        print(f"[DevRebase] Worktree 不存在: {DEV_WORKTREE}（略過）")
        return 0

    # 單日鎖
    today = _today_taipei()
    last = _get_last_run_date()
    if last == today:
        print(f"[DevRebase] 今日已執行過（{last}），跳過")
        return 0

    # Lockfile
    if not _check_lockfile():
        return 0

    try:
        # 先 fetch origin（與 main worktree 共用 .git）
        ret, _out, err = _run(["git", "fetch", "--tags", "--force", "origin"], PROJECT_ROOT)
        if ret != 0:
            print(f"[DevRebase] git fetch 失敗: {err}")
            return 1

        # 在 dev worktree rebase onto main
        ret, _out, err = _run(["git", "rebase", "main"], DEV_WORKTREE)
        if ret != 0:
            # rebase 衝突 → abort，保持 dev 不動
            _run(["git", "rebase", "--abort"], DEV_WORKTREE)
            print(f"[DevRebase] Rebase 衝突，已 abort（不重試）: {err}")
            # 標記今日已執行，避免無限重試
            _mark_last_run_date(today)
            return 1

        print("[DevRebase] Dev worktree rebased onto main")
        _mark_last_run_date(today)
        return 0

    finally:
        _release_lockfile()


if __name__ == "__main__":
    sys.exit(main())
