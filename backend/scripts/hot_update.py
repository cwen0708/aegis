#!/usr/bin/env python3
"""
Aegis Hot Update Script
獨立執行的熱更新腳本，與主進程分離
"""
import os
import sys
import subprocess
import time
from pathlib import Path

# 設定專案路徑
SCRIPT_DIR = Path(__file__).parent
BACKEND_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = BACKEND_DIR.parent

# 加入 backend 到 path
sys.path.insert(0, str(BACKEND_DIR))

from sqlmodel import Session
from app.database import engine
from app.models.core import SystemSetting


def update_status(stage: str, progress: int, message: str, error: str = ""):
    """更新 DB 中的狀態"""
    with Session(engine) as session:
        for key, value in [
            ("update_stage", stage),
            ("update_progress", str(progress)),
            ("update_message", message),
            ("update_error", error),
            ("update_is_updating", "true" if stage not in ("done", "failed", "idle") else "false"),
        ]:
            setting = session.get(SystemSetting, key)
            if setting:
                setting.value = value
            else:
                setting = SystemSetting(key=key, value=value)
            session.add(setting)
        session.commit()


def run_command(cmd: list, cwd: str = None) -> tuple:
    """執行命令並返回結果"""
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True
    )
    return proc.returncode, proc.stdout, proc.stderr


def main():
    try:
        update_status("downloading", 0, "正在拉取最新代碼...")

        # Git pull
        ret, out, err = run_command(["git", "pull", "--ff-only"], cwd=str(PROJECT_ROOT))
        if ret != 0:
            update_status("failed", 0, "git pull 失敗", err)
            return 1

        update_status("building", 30, "正在安裝 Python 依賴...")

        # Pip install
        venv_python = BACKEND_DIR / "venv" / "bin" / "python"
        if venv_python.exists():
            ret, out, err = run_command(
                [str(venv_python), "-m", "pip", "install", "-r", "requirements.txt", "-q"],
                cwd=str(BACKEND_DIR)
            )

        update_status("building", 50, "正在建構前端...")

        # Frontend build（限制記憶體避免 OOM）
        frontend_dir = PROJECT_ROOT / "frontend"
        if (frontend_dir / "package.json").exists():
            # 設定 Node.js 記憶體限制（512MB），避免在低記憶體 VM 上 OOM
            node_env = os.environ.copy()
            node_env["NODE_OPTIONS"] = "--max-old-space-size=512"

            # 檢查 package.json 是否有變動，有才跑 npm install
            ret, diff_out, _ = run_command(
                ["git", "diff", "--name-only", "HEAD~1", "HEAD", "--", "frontend/package.json"],
                cwd=str(PROJECT_ROOT)
            )
            if "package.json" in diff_out:
                update_status("building", 55, "正在安裝前端依賴...")
                proc = subprocess.run(
                    ["npm", "install", "--prefer-offline"],
                    cwd=str(frontend_dir),
                    env=node_env,
                    capture_output=True,
                    text=True
                )

            update_status("building", 65, "正在建構前端（這可能需要幾分鐘）...")

            proc = subprocess.run(
                ["npm", "run", "build"],
                cwd=str(frontend_dir),
                env=node_env,
                capture_output=True,
                text=True
            )
            if proc.returncode != 0:
                update_status("failed", 50, "前端建構失敗", proc.stderr[:500])
                return 1

        update_status("applying", 80, "正在重啟服務...")
        # 注意：系統排程同步由 main.py 啟動時自動執行，無需在此執行 seed.py

        # 先標記完成（因為重啟後這個進程也會被殺掉）
        update_status("done", 100, "更新完成，服務重啟中...")

        # 重啟服務（用 systemctl，這會殺掉 aegis 但這個腳本是獨立的）
        time.sleep(1)  # 給 DB 寫入一點時間

        subprocess.run(["sudo", "systemctl", "restart", "aegis"], check=False)
        subprocess.run(["sudo", "systemctl", "restart", "aegis-worker"], check=False)

        return 0

    except Exception as e:
        update_status("failed", 0, "更新失敗", str(e))
        return 1


if __name__ == "__main__":
    sys.exit(main())
