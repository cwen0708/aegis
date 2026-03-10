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

        # Frontend build
        frontend_dir = PROJECT_ROOT / "frontend"
        if (frontend_dir / "package.json").exists():
            run_command(["npm", "install"], cwd=str(frontend_dir))
            ret, out, err = run_command(["npm", "run", "build"], cwd=str(frontend_dir))
            if ret != 0:
                update_status("failed", 50, "前端建構失敗", err)
                return 1

        update_status("applying", 70, "正在同步系統資料...")

        # 執行 seed.py 同步新的系統排程等資料
        # 使用 sudo -u cwen0 確保以正確用戶執行（避免 DB 權限問題）
        python_cmd = str(venv_python) if venv_python.exists() else "python3"
        ret, out, err = run_command(
            ["sudo", "-u", "cwen0", python_cmd, "seed.py"],
            cwd=str(BACKEND_DIR)
        )
        if ret != 0:
            print(f"Warning: seed.py failed: {err}")

        update_status("applying", 80, "正在重啟服務...")

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
