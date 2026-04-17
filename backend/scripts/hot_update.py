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

# Debounce lockfile — 5 分鐘內不重複執行
LOCK_FILE = BACKEND_DIR / ".hot_update.lock"
DEBOUNCE_SECONDS = 300  # 5 minutes


def _check_debounce() -> bool:
    """檢查 lockfile，回傳 True 表示可以執行"""
    try:
        if LOCK_FILE.exists():
            age = time.time() - LOCK_FILE.stat().st_mtime
            if age < DEBOUNCE_SECONDS:
                print(f"[HotUpdate] Debounce: 上次執行 {int(age)}s 前（< {DEBOUNCE_SECONDS}s），跳過")
                return False
        LOCK_FILE.write_text(str(int(time.time())))
        return True
    except Exception:
        return True  # lockfile 操作失敗時不阻擋更新


def _release_lock():
    """更新完成後刪除 lockfile（允許下次立即執行）"""
    try:
        LOCK_FILE.unlink(missing_ok=True)
    except Exception:
        pass


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


def resume_worker():
    """更新失敗時恢復 Worker 到更新前的狀態"""
    try:
        with Session(engine) as session:
            # 讀取更新前的狀態
            before = session.get(SystemSetting, "worker_paused_before_update")
            was_paused = before and before.value == "true"
            if was_paused:
                # 更新前就是暫停的，保持暫停
                return
            paused = session.get(SystemSetting, "worker_paused")
            if paused and paused.value == "true":
                paused.value = "false"
                session.add(paused)
                session.commit()
    except Exception:
        pass


def run_command(cmd: list, cwd: str = None) -> tuple:
    """執行命令並返回結果"""
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True
    )
    return proc.returncode, proc.stdout, proc.stderr


def trigger_smart_update(local_commits: int):
    """本地有進化 commit，建立智慧更新卡片給愛吉絲"""
    import json
    import urllib.request

    API = "http://127.0.0.1:8899/api/v1"

    # 取得上游和本地的 commit 列表
    _, upstream_log, _ = run_command(
        ["git", "log", "HEAD..origin/main", "--oneline"], cwd=str(PROJECT_ROOT)
    )
    _, local_log, _ = run_command(
        ["git", "log", "origin/main..HEAD", "--oneline"], cwd=str(PROJECT_ROOT)
    )

    # 動態查愛吉絲的收件匣 list_id
    try:
        resp = urllib.request.urlopen(f"{API}/projects/1/board", timeout=10)
        board = json.loads(resp.read())
        aegis_list = None
        for stage in board:
            if "愛吉絲" in stage.get("name", ""):
                aegis_list = stage["id"]
                break
        if not aegis_list:
            print("找不到愛吉絲收件匣，跳過智慧更新")
            return
    except Exception as e:
        print(f"查詢看板失敗: {e}")
        return

    card = {
        "title": "智慧更新: 合併上游新版本",
        "list_id": aegis_list,
        "project_id": 1,
        "description": (
            f"## 上游有新版本\n\n"
            f"### 上游新 commit\n```\n{upstream_log.strip()}\n```\n\n"
            f"### 本地進化 commit（{local_commits} 個）\n```\n{local_log.strip()}\n```\n\n"
            f"請執行 smart-update skill 合併上游變更並部署。"
        ),
    }

    try:
        data = json.dumps(card).encode("utf-8")
        req = urllib.request.Request(
            f"{API}/cards/", data=data,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        resp = urllib.request.urlopen(req, timeout=10)
        result = json.loads(resp.read())
        card_id = result.get("id")

        # 觸發卡片
        urllib.request.urlopen(urllib.request.Request(
            f"{API}/cards/{card_id}/trigger", method="POST",
        ), timeout=10)
        print(f"智慧更新卡片已建立: #{card_id}")
    except Exception as e:
        print(f"建立智慧更新卡片失敗: {e}")


def main():
    # Debounce 檢查
    if not _check_debounce():
        return 0

    try:
        update_status("downloading", 0, "正在拉取最新代碼...")

        # 先 fetch（不改本地檔案）
        run_command(["git", "fetch", "--tags", "--force", "origin"], cwd=str(PROJECT_ROOT))

        # 偵測本地有沒有進化 commit（dev dir 的自我開發產物）
        ret, ahead_count, _ = run_command(
            ["git", "rev-list", "origin/main..HEAD", "--count"], cwd=str(PROJECT_ROOT)
        )
        local_commits = int(ahead_count.strip()) if ret == 0 and ahead_count.strip().isdigit() else 0

        if local_commits > 0:
            # 有本地進化 → 交給愛吉絲智慧更新
            update_status("done", 100,
                          f"偵測到 {local_commits} 個本地進化 commit，已建立智慧更新卡片")
            trigger_smart_update(local_commits)
            resume_worker()
            return 0

        # 沒有本地進化 → 直接自動更新（git reset --hard，確保乾淨）
        run_command(["git", "checkout", "--", "backend/VERSION"], cwd=str(PROJECT_ROOT))
        ret, out, err = run_command(
            ["git", "reset", "--hard", "origin/main"], cwd=str(PROJECT_ROOT)
        )
        if ret != 0:
            update_status("failed", 0, "git reset 失敗", err)
            resume_worker()
            return 1

        # 同步 dev worktree（AI 開發分支）到最新 main
        DEV_WORKTREE = Path("/home/cwen0708/projects/Aegis-dev")
        if DEV_WORKTREE.exists():
            try:
                # 先 fetch（共用 .git，main worktree 已 fetch 過）
                # 再 rebase dev onto main
                ret_rb, _, err_rb = run_command(
                    ["git", "rebase", "main"], cwd=str(DEV_WORKTREE)
                )
                if ret_rb != 0:
                    # rebase 衝突 → abort，保持 dev 不動（不影響部署）
                    run_command(["git", "rebase", "--abort"], cwd=str(DEV_WORKTREE))
                    print(f"[HotUpdate] Dev rebase conflict, skipped: {err_rb}")
                else:
                    print("[HotUpdate] Dev worktree rebased onto main")
            except Exception as e:
                print(f"[HotUpdate] Dev rebase failed: {e}")

        update_status("building", 30, "正在安裝 Python 依賴...")

        # Pip install
        venv_python = BACKEND_DIR / "venv" / "bin" / "python"
        if venv_python.exists():
            ret, out, err = run_command(
                [str(venv_python), "-m", "pip", "install", "-r", "requirements.txt", "-q"],
                cwd=str(BACKEND_DIR)
            )

        update_status("building", 50, "正在下載前端建構產物...")

        # 從 GitHub Release 下載 CI 預建好的前端 dist
        frontend_dir = PROJECT_ROOT / "frontend"
        dist_dir = frontend_dir / "dist"

        # 取得當前 git tag
        ret, tag_out, _ = run_command(
            ["git", "describe", "--tags", "--abbrev=0"],
            cwd=str(PROJECT_ROOT)
        )
        current_tag = tag_out.strip() if ret == 0 and tag_out.strip() else None

        if current_tag:
            dist_downloaded = False
            repo = "cwen0708/aegis"
            tarball_url = f"https://github.com/{repo}/releases/download/{current_tag}/frontend-dist.tar.gz"
            tarball_path = PROJECT_ROOT / "frontend-dist.tar.gz"

            update_status("building", 55, f"正在下載前端 ({current_tag})...")

            ret, _, err = run_command(
                ["curl", "-sL", "-o", str(tarball_path), "-w", "%{http_code}", tarball_url]
            )
            if ret == 0 and tarball_path.exists() and tarball_path.stat().st_size > 1000:
                # 清空舊 dist，解壓新的
                import shutil
                if dist_dir.exists():
                    shutil.rmtree(dist_dir)
                dist_dir.mkdir(parents=True, exist_ok=True)

                ret, _, err = run_command(
                    ["tar", "-xzf", str(tarball_path), "-C", str(dist_dir)]
                )
                tarball_path.unlink(missing_ok=True)

                if ret == 0:
                    dist_downloaded = True
                    update_status("building", 70, "前端下載完成")
                else:
                    update_status("building", 60, f"解壓失敗，嘗試本地建構... {err[:200]}")

            if not dist_downloaded:
                # Fallback：本地建構（相容舊版 Release 無 dist 的情況）
                update_status("building", 60, "Release 無前端產物，本地建構中...")
                node_env = os.environ.copy()
                node_env["NODE_OPTIONS"] = "--max-old-space-size=1024"

                proc = subprocess.run(
                    ["npm", "install", "--prefer-offline"],
                    cwd=str(frontend_dir),
                    env=node_env,
                    capture_output=True,
                    text=True
                )
                proc = subprocess.run(
                    ["npm", "run", "build"],
                    cwd=str(frontend_dir),
                    env=node_env,
                    capture_output=True,
                    text=True
                )
                if proc.returncode != 0:
                    update_status("failed", 50, "前端建構失敗", proc.stderr[:500])
                    resume_worker()
                    return 1

        update_status("applying", 80, "正在更新版本號並重啟服務...")

        # SSOT: 從 git tag 寫入 VERSION 檔（僅在建構全程成功後執行）
        # 失敗路徑已於前面 return，不會走到此處，故 VERSION 不會被錯誤覆蓋。
        ret, tag_out, _ = run_command(
            ["git", "describe", "--tags", "--abbrev=0"],
            cwd=str(PROJECT_ROOT)
        )
        if ret == 0 and tag_out.strip():
            version_str = tag_out.strip().lstrip("v")
            version_file = BACKEND_DIR / "VERSION"
            try:
                version_file.write_text(version_str, encoding="utf-8")
                print(f"[HotUpdate] VERSION 已更新: {version_str}")
            except OSError as ve:
                # VERSION 寫入失敗不中斷部署（git 為真實 SSOT），僅記錄
                print(f"[HotUpdate] VERSION 寫入失敗（忽略）: {ve}")
        else:
            print("[HotUpdate] git describe 失敗，VERSION 保持不變")

        # 注意：系統排程同步由 main.py 啟動時自動執行，無需在此執行 seed.py

        # 先標記完成（因為重啟後這個進程也會被殺掉）
        update_status("done", 100, "更新完成，服務重啟中...")

        # 更新成功，釋放 lockfile（允許下次更新）
        _release_lock()

        # 重啟服務：先 worker 再 aegis（因為 aegis 重啟會殺掉本進程的父進程）
        time.sleep(1)  # 給 DB 寫入一點時間

        subprocess.run(["sudo", "systemctl", "restart", "aegis-worker"], check=False)
        time.sleep(1)
        subprocess.run(["sudo", "systemctl", "restart", "aegis"], check=False)

        return 0

    except Exception as e:
        update_status("failed", 0, "更新失敗", str(e))
        resume_worker()
        # 失敗時保留 lockfile，讓 debounce 繼續生效
        return 1


if __name__ == "__main__":
    sys.exit(main())
