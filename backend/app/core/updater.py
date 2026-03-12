"""
Aegis Hot Update System
熱更新核心模組 - 版本檢查、下載、套用、回滾
"""
import asyncio
import logging
import os
import subprocess
import shutil
import re
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# 更新階段
UPDATE_STAGE_IDLE = "idle"
UPDATE_STAGE_CHECKING = "checking"
UPDATE_STAGE_DOWNLOADING = "downloading"
UPDATE_STAGE_BUILDING = "building"
UPDATE_STAGE_WAITING = "waiting"  # 等待任務完成
UPDATE_STAGE_APPLYING = "applying"
UPDATE_STAGE_DONE = "done"
UPDATE_STAGE_FAILED = "failed"


@dataclass
class UpdateState:
    """更新狀態"""
    current_version: str = ""
    latest_version: str = ""
    has_update: bool = False
    is_updating: bool = False
    stage: str = UPDATE_STAGE_IDLE
    progress: int = 0  # 0-100
    message: str = ""
    error: str = ""
    available_versions: list = field(default_factory=list)


# 全域狀態
_state = UpdateState()


def get_current_version() -> str:
    """讀取當前版本號"""
    version_file = Path(__file__).parent.parent.parent / "VERSION"
    if version_file.exists():
        return version_file.read_text().strip()
    return "0.0.0"


def parse_version(version: str) -> tuple:
    """解析版本號為可比較的 tuple

    v0.2.1       → (0, 2, 1, 1, 0)    — 正式版（dev_flag=1 排在 dev 之後）
    v0.2.2-dev.9 → (0, 2, 2, 0, 9)    — dev 版（dev_flag=0）
    """
    v = version.lstrip("v")
    match = re.match(r"(\d+)\.(\d+)\.(\d+)(?:-dev\.(\d+))?", v)
    if match:
        major, minor, patch = int(match.group(1)), int(match.group(2)), int(match.group(3))
        dev_num = match.group(4)
        if dev_num is not None:
            return (major, minor, patch, 0, int(dev_num))  # dev 版
        return (major, minor, patch, 1, 0)  # 正式版排在同版 dev 之後
    return (0, 0, 0, 0, 0)


def is_newer_version(latest: str, current: str) -> bool:
    """比較版本號"""
    return parse_version(latest) > parse_version(current)


async def check_for_updates(repo: str = "cwen0708/aegis", channel: str = "development") -> UpdateState:
    """
    檢查 GitHub 是否有新版本

    Args:
        repo: GitHub 倉庫路徑
        channel: 更新頻道
            - "development": 所有 v*.*.* 版本（開發版）
            - "stable": 僅 v*.*.*-stable 版本（穩定版）
    """
    global _state
    _state.stage = UPDATE_STAGE_CHECKING
    _state.message = "正在檢查更新..."
    _state.error = ""

    try:
        import httpx

        _state.current_version = get_current_version()

        # 查詢 GitHub API 取得 tags
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://api.github.com/repos/{repo}/tags",
                headers={"Accept": "application/vnd.github.v3+json"},
                timeout=30.0
            )

            if resp.status_code != 200:
                raise Exception(f"GitHub API 回傳 {resp.status_code}")

            tags = resp.json()

        # 根據頻道過濾 tags
        if channel == "stable":
            # 穩定版：僅 v*.*.*-stable
            tag_pattern = re.compile(r"^v\d+\.\d+\.\d+-stable$")
            channel_name = "穩定版"
        else:
            # 開發版（預設）：所有 v*.*.* 和 v*.*.*-dev.*
            tag_pattern = re.compile(r"^v\d+\.\d+\.\d+(-dev\.\d+)?$")
            channel_name = "開發版"

        filtered_tags = [t["name"] for t in tags if tag_pattern.match(t["name"])]

        if not filtered_tags:
            _state.latest_version = _state.current_version
            _state.has_update = False
            _state.message = f"已是最新{channel_name}"
            _state.available_versions = []
        else:
            # 排序取得最新版本
            filtered_tags.sort(key=parse_version, reverse=True)
            # 穩定版去掉 -stable 後綴來比較版本號
            latest_tag = filtered_tags[0]
            _state.latest_version = latest_tag.lstrip("v").replace("-stable", "")
            _state.has_update = is_newer_version(_state.latest_version, _state.current_version)
            _state.available_versions = filtered_tags[:10]  # 保留最近 10 個版本

            if _state.has_update:
                _state.message = f"發現新{channel_name} {_state.latest_version}"
            else:
                _state.message = f"已是最新{channel_name}"

        _state.stage = UPDATE_STAGE_IDLE

    except Exception as e:
        logger.error(f"檢查更新失敗: {e}")
        _state.error = str(e)
        _state.stage = UPDATE_STAGE_FAILED
        _state.message = "檢查更新失敗"

    return _state


def get_update_state() -> UpdateState:
    """取得當前更新狀態（從 DB 讀取）"""
    from app.database import engine
    from app.models.core import SystemSetting
    from sqlmodel import Session

    _state.current_version = get_current_version()

    # 從 DB 讀取更新狀態（供獨立腳本更新）
    with Session(engine) as session:
        stage = session.get(SystemSetting, "update_stage")
        progress = session.get(SystemSetting, "update_progress")
        message = session.get(SystemSetting, "update_message")
        error = session.get(SystemSetting, "update_error")
        is_updating = session.get(SystemSetting, "update_is_updating")

        if stage:
            _state.stage = stage.value
        if progress:
            _state.progress = int(progress.value)
        if message:
            _state.message = message.value
        if error:
            _state.error = error.value
        if is_updating:
            _state.is_updating = is_updating.value == "true"

    return _state


def is_deployed_environment() -> bool:
    """判斷是否為部署環境（Linux 伺服器）"""
    import platform
    # Linux = 部署環境，Windows = 本地開發
    return platform.system() == "Linux"


def is_symlink_deployment() -> bool:
    """判斷是否為符號連結部署架構"""
    current_link = Path(__file__).parent.parent.parent.parent / "current"
    releases_dir = Path(__file__).parent.parent.parent.parent / "releases"
    return current_link.is_symlink() or releases_dir.exists()


def get_deployment_paths() -> dict:
    """取得部署環境的路徑"""
    # backend/app/core/updater.py -> backend -> Aegis (或 current)
    base = Path(__file__).parent.parent.parent.parent

    if is_deployed_environment():
        return {
            "base": base,
            "current": base / "current",
            "releases": base / "releases",
            "shared": base / "shared",
            "update_temp": base / ".update",
        }
    else:
        # 本地開發環境
        return {
            "base": Path(__file__).parent.parent.parent,  # backend/
            "current": None,
            "releases": None,
            "shared": None,
            "update_temp": None,
        }


async def download_version(version: str, repo: str = "cwen0708/aegis") -> bool:
    """
    下載指定版本到 releases 目錄
    """
    global _state

    if not is_deployed_environment():
        _state.error = "本地開發環境不支援熱更新"
        _state.stage = UPDATE_STAGE_FAILED
        return False

    paths = get_deployment_paths()
    version_tag = f"v{version.lstrip('v')}"
    release_dir = paths["releases"] / version_tag

    if release_dir.exists():
        _state.message = f"版本 {version_tag} 已存在"
        return True

    _state.stage = UPDATE_STAGE_DOWNLOADING
    _state.progress = 0
    _state.message = f"正在下載 {version_tag}..."

    try:
        # 建立暫存目錄
        temp_dir = paths["update_temp"] / "downloading"
        temp_dir.mkdir(parents=True, exist_ok=True)

        # 使用 git clone 下載指定 tag
        clone_path = temp_dir / version_tag
        if clone_path.exists():
            shutil.rmtree(clone_path)

        _state.progress = 10

        proc = await asyncio.create_subprocess_exec(
            "git", "clone", "--depth", "1", "--branch", version_tag,
            f"https://github.com/{repo}.git", str(clone_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise Exception(f"git clone 失敗: {stderr.decode()}")

        _state.progress = 50
        _state.message = "正在安裝依賴..."

        # 移動到 releases 目錄
        paths["releases"].mkdir(parents=True, exist_ok=True)
        shutil.move(str(clone_path), str(release_dir))

        _state.progress = 100
        _state.message = f"版本 {version_tag} 下載完成"
        _state.stage = UPDATE_STAGE_IDLE

        return True

    except Exception as e:
        logger.error(f"下載版本失敗: {e}")
        _state.error = str(e)
        _state.stage = UPDATE_STAGE_FAILED
        return False


async def build_version(version: str) -> bool:
    """
    在指定版本目錄執行建構（安裝依賴、npm build）
    """
    global _state

    if not is_deployed_environment():
        return False

    paths = get_deployment_paths()
    version_tag = f"v{version.lstrip('v')}"
    release_dir = paths["releases"] / version_tag

    if not release_dir.exists():
        _state.error = f"版本 {version_tag} 不存在"
        _state.stage = UPDATE_STAGE_FAILED
        return False

    _state.stage = UPDATE_STAGE_BUILDING
    _state.progress = 0
    _state.message = "正在安裝 Python 依賴..."

    try:
        # 建立符號連結到 shared 資源
        shared = paths["shared"]
        if shared.exists():
            # 連結 venv
            venv_link = release_dir / "backend" / "venv"
            if not venv_link.exists() and (shared / "venv").exists():
                venv_link.symlink_to(shared / "venv")

            # 連結 data
            data_link = release_dir / "backend" / "data"
            if not data_link.exists() and (shared / "data").exists():
                data_link.symlink_to(shared / "data")

            # 連結 uploads
            uploads_link = release_dir / "backend" / "uploads"
            if not uploads_link.exists() and (shared / "uploads").exists():
                uploads_link.symlink_to(shared / "uploads")

            # 連結 .aegis
            aegis_link = release_dir / ".aegis"
            if not aegis_link.exists() and (shared / ".aegis").exists():
                aegis_link.symlink_to(shared / ".aegis")

        _state.progress = 30

        # 安裝 Python 依賴（如果 requirements.txt 有變更）
        backend_dir = release_dir / "backend"
        venv_python = shared / "venv" / "bin" / "python" if shared else backend_dir / "venv" / "bin" / "python"

        if venv_python.exists():
            proc = await asyncio.create_subprocess_exec(
                str(venv_python), "-m", "pip", "install", "-r", "requirements.txt",
                cwd=str(backend_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await proc.communicate()

        _state.progress = 60
        _state.message = "正在下載前端建構產物..."

        # 從 GitHub Release 下載 CI 預建好的前端 dist
        frontend_dir = release_dir / "frontend"
        dist_dir = frontend_dir / "dist"
        repo = "cwen0708/aegis"
        tarball_url = f"https://github.com/{repo}/releases/download/{version_tag}/frontend-dist.tar.gz"
        tarball_path = release_dir / "frontend-dist.tar.gz"

        dist_downloaded = False
        try:
            import httpx
            async with httpx.AsyncClient(follow_redirects=True) as client:
                resp = await client.get(tarball_url, timeout=60.0)
                if resp.status_code == 200 and len(resp.content) > 1000:
                    tarball_path.write_bytes(resp.content)

                    if dist_dir.exists():
                        shutil.rmtree(dist_dir)
                    dist_dir.mkdir(parents=True, exist_ok=True)

                    proc = await asyncio.create_subprocess_exec(
                        "tar", "-xzf", str(tarball_path), "-C", str(dist_dir),
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    await proc.communicate()
                    tarball_path.unlink(missing_ok=True)

                    if proc.returncode == 0:
                        dist_downloaded = True
                        _state.progress = 80
        except Exception as dl_err:
            logger.warning(f"下載前端 dist 失敗: {dl_err}")

        if not dist_downloaded:
            # Fallback：本地建構（相容舊版 Release 無 dist 的情況）
            _state.message = "Release 無前端產物，本地建構中..."
            if (frontend_dir / "package.json").exists():
                proc = await asyncio.create_subprocess_exec(
                    "npm", "install",
                    cwd=str(frontend_dir),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                await proc.communicate()

                _state.progress = 80

                proc = await asyncio.create_subprocess_exec(
                    "npm", "run", "build",
                    cwd=str(frontend_dir),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await proc.communicate()

                if proc.returncode != 0:
                    raise Exception(f"前端建構失敗: {stderr.decode()}")

        _state.progress = 100
        _state.message = f"版本 {version_tag} 建構完成"
        _state.stage = UPDATE_STAGE_IDLE

        return True

    except Exception as e:
        logger.error(f"建構版本失敗: {e}")
        _state.error = str(e)
        _state.stage = UPDATE_STAGE_FAILED
        return False


async def wait_for_tasks_completion(timeout: int = 300) -> bool:
    """
    等待所有執行中的任務完成
    """
    global _state
    from app.database import engine
    from app.models.core import CardIndex, SystemSetting
    from sqlmodel import Session, select

    _state.stage = UPDATE_STAGE_WAITING
    _state.message = "等待執行中的任務完成..."

    # 先暫停 Worker
    with Session(engine) as session:
        paused = session.get(SystemSetting, "worker_paused")
        if paused:
            paused.value = "true"
        else:
            paused = SystemSetting(key="worker_paused", value="true")
        session.add(paused)
        session.commit()

    start_time = asyncio.get_event_loop().time()

    while True:
        with Session(engine) as session:
            running = session.exec(
                select(CardIndex).where(CardIndex.status == "running")
            ).all()

            if not running:
                _state.message = "所有任務已完成"
                return True

            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed > timeout:
                _state.error = f"等待超時，仍有 {len(running)} 個任務執行中"
                _state.stage = UPDATE_STAGE_FAILED
                return False

            _state.message = f"等待 {len(running)} 個任務完成... ({int(elapsed)}s/{timeout}s)"

        await asyncio.sleep(5)


async def apply_update(version: str) -> bool:
    """
    套用更新：切換符號連結並重啟服務
    """
    global _state

    if not is_deployed_environment():
        _state.error = "本地開發環境不支援熱更新"
        _state.stage = UPDATE_STAGE_FAILED
        return False

    paths = get_deployment_paths()
    version_tag = f"v{version.lstrip('v')}"
    release_dir = paths["releases"] / version_tag
    current_link = paths["current"]

    if not release_dir.exists():
        _state.error = f"版本 {version_tag} 不存在"
        _state.stage = UPDATE_STAGE_FAILED
        return False

    _state.stage = UPDATE_STAGE_APPLYING
    _state.message = "正在套用更新..."

    try:
        # 記錄舊版本（用於回滾）
        old_version = None
        if current_link.is_symlink():
            old_target = current_link.resolve()
            old_version = old_target.name

        # 切換符號連結
        temp_link = paths["base"] / "current.new"
        if temp_link.exists():
            temp_link.unlink()

        temp_link.symlink_to(release_dir)

        # 原子性替換
        temp_link.rename(current_link)

        _state.progress = 50
        _state.message = "正在重啟服務..."

        # 重啟 systemd 服務
        # 注意：必須先重啟 worker 再重啟 aegis，因為重啟 aegis 會殺掉本進程
        proc = await asyncio.create_subprocess_exec(
            "sudo", "systemctl", "restart", "aegis-worker",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await proc.communicate()

        _state.progress = 80
        _state.message = "正在重啟 API 服務..."

        # 重啟 aegis（本進程會被殺掉，之後的程式碼不會執行）
        proc = await asyncio.create_subprocess_exec(
            "sudo", "systemctl", "restart", "aegis",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await proc.communicate()

        # 以下可能不會執行（因為 aegis 重啟會殺掉本進程）
        _state.message = "正在驗證服務..."

        # 等待服務啟動
        await asyncio.sleep(5)

        # 健康檢查
        import httpx
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get("http://localhost:8899/health", timeout=10.0)
                if resp.status_code != 200:
                    raise Exception("健康檢查失敗")
            except Exception as e:
                # 回滾
                if old_version:
                    logger.warning(f"健康檢查失敗，回滾到 {old_version}")
                    await rollback(old_version)
                raise

        _state.progress = 100
        _state.stage = UPDATE_STAGE_DONE
        _state.message = f"已更新到 {version_tag}"
        _state.current_version = version.lstrip("v")
        _state.has_update = False

        return True

    except Exception as e:
        logger.error(f"套用更新失敗: {e}")
        _state.error = str(e)
        _state.stage = UPDATE_STAGE_FAILED
        return False

    finally:
        # 無論成功或失敗，都恢復 Worker
        try:
            from app.database import engine
            from app.models.core import SystemSetting
            from sqlmodel import Session

            with Session(engine) as session:
                paused = session.get(SystemSetting, "worker_paused")
                if paused and paused.value == "true":
                    paused.value = "false"
                    session.add(paused)
                    session.commit()
                    logger.info("Worker 已自動恢復")
        except Exception as resume_err:
            logger.error(f"恢復 Worker 失敗: {resume_err}")


async def rollback(version: str = None) -> bool:
    """
    回滾到指定版本（預設為上一版）
    """
    global _state

    if not is_deployed_environment():
        _state.error = "本地開發環境不支援回滾"
        _state.stage = UPDATE_STAGE_FAILED
        return False

    paths = get_deployment_paths()

    if version:
        version_tag = f"v{version.lstrip('v')}"
    else:
        # 找上一個版本
        releases = sorted(paths["releases"].iterdir(), key=lambda p: parse_version(p.name), reverse=True)
        current_version = get_current_version()
        for release in releases:
            if parse_version(release.name) < parse_version(current_version):
                version_tag = release.name
                break
        else:
            _state.error = "找不到可回滾的版本"
            _state.stage = UPDATE_STAGE_FAILED
            return False

    release_dir = paths["releases"] / version_tag
    if not release_dir.exists():
        _state.error = f"版本 {version_tag} 不存在"
        _state.stage = UPDATE_STAGE_FAILED
        return False

    _state.stage = UPDATE_STAGE_APPLYING
    _state.message = f"正在回滾到 {version_tag}..."

    try:
        current_link = paths["current"]
        temp_link = paths["base"] / "current.new"

        if temp_link.exists():
            temp_link.unlink()

        temp_link.symlink_to(release_dir)
        temp_link.rename(current_link)

        # 重啟服務（先 worker 再 aegis，因為重啟 aegis 會殺掉本進程）
        proc = await asyncio.create_subprocess_exec(
            "sudo", "systemctl", "restart", "aegis-worker",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await proc.communicate()

        proc = await asyncio.create_subprocess_exec(
            "sudo", "systemctl", "restart", "aegis",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await proc.communicate()

        _state.stage = UPDATE_STAGE_DONE
        _state.message = f"已回滾到 {version_tag}"
        _state.current_version = version_tag.lstrip("v")

        return True

    except Exception as e:
        logger.error(f"回滾失敗: {e}")
        _state.error = str(e)
        _state.stage = UPDATE_STAGE_FAILED
        return False


async def cleanup_old_versions(keep: int = 3) -> int:
    """
    清理舊版本，保留最近 N 個
    """
    if not is_deployed_environment():
        return 0

    paths = get_deployment_paths()
    releases_dir = paths["releases"]

    if not releases_dir.exists():
        return 0

    # 取得所有版本並排序
    versions = sorted(
        [d for d in releases_dir.iterdir() if d.is_dir()],
        key=lambda p: parse_version(p.name),
        reverse=True
    )

    # 保留當前版本和最近 N 個
    current = get_current_version()
    to_delete = []
    kept = 0

    for v in versions:
        if v.name.lstrip("v") == current:
            continue  # 永不刪除當前版本
        if kept < keep:
            kept += 1
            continue
        to_delete.append(v)

    # 刪除舊版本
    for v in to_delete:
        try:
            shutil.rmtree(v)
            logger.info(f"已刪除舊版本: {v.name}")
        except Exception as e:
            logger.warning(f"刪除 {v.name} 失敗: {e}")

    return len(to_delete)


# ==========================================
# Git Pull 更新流程（非符號連結架構）
# ==========================================
def _update_db_status(stage: str, progress: int, message: str, error: str = "", is_updating: bool = True):
    """更新 DB 中的狀態"""
    from app.database import engine
    from app.models.core import SystemSetting
    from sqlmodel import Session

    with Session(engine) as session:
        for key, value in [
            ("update_stage", stage),
            ("update_progress", str(progress)),
            ("update_message", message),
            ("update_error", error),
            ("update_is_updating", "true" if is_updating else "false"),
        ]:
            setting = session.get(SystemSetting, key)
            if setting:
                setting.value = value
            else:
                setting = SystemSetting(key=key, value=value)
            session.add(setting)
        session.commit()


async def git_pull_update() -> bool:
    """
    啟動獨立的熱更新腳本（與主進程分離）
    """
    global _state

    if not is_deployed_environment():
        _state.error = "本地開發環境不支援熱更新"
        _state.stage = UPDATE_STAGE_FAILED
        return False

    try:
        import subprocess

        # 更新初始狀態
        _update_db_status(UPDATE_STAGE_DOWNLOADING, 0, "正在啟動更新程序...")
        _state.stage = UPDATE_STAGE_DOWNLOADING
        _state.progress = 0
        _state.message = "正在啟動更新程序..."
        _state.is_updating = True

        # 取得更新腳本路徑
        script_path = Path(__file__).parent.parent.parent / "scripts" / "hot_update.py"
        venv_python = Path(__file__).parent.parent.parent / "venv" / "bin" / "python"

        if not script_path.exists():
            raise Exception(f"更新腳本不存在: {script_path}")

        python_cmd = str(venv_python) if venv_python.exists() else "python3"

        # 啟動獨立進程執行更新（與當前進程分離）
        subprocess.Popen(
            [python_cmd, str(script_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,  # 分離進程組
        )

        logger.info("Hot update script started in background")
        return True

    except Exception as e:
        logger.error(f"啟動更新腳本失敗: {e}")
        _state.error = str(e)
        _state.stage = UPDATE_STAGE_FAILED
        _update_db_status(UPDATE_STAGE_FAILED, 0, "啟動更新腳本失敗", str(e), False)
        return False


# ==========================================
# 完整更新流程
# ==========================================
async def full_update(version: str = None, wait_timeout: int = 300) -> bool:
    """
    執行完整更新流程
    - 符號連結架構：下載 → 建構 → 等待任務 → 套用
    - Git 架構：git pull → 建構 → 重啟
    """
    global _state

    _state.is_updating = True
    _state.error = ""

    try:
        # 1. 檢查更新（如果沒指定版本）
        if not version:
            await check_for_updates()
            if not _state.has_update:
                _state.message = "已是最新版本"
                _state.is_updating = False
                return True
            version = _state.latest_version

        # 2. 等待任務完成
        if not await wait_for_tasks_completion(wait_timeout):
            return False

        # 3. 根據部署架構選擇更新方式
        if is_symlink_deployment():
            # 符號連結架構
            if not await download_version(version):
                return False
            if not await build_version(version):
                return False
            if not await apply_update(version):
                return False
            await cleanup_old_versions()
        else:
            # Git 架構
            if not await git_pull_update():
                return False

        return True

    finally:
        _state.is_updating = False
        # 無論成功或失敗，確保 Worker 恢復運作
        try:
            from app.database import engine as _engine
            from app.models.core import SystemSetting
            from sqlmodel import Session as _Session

            with _Session(_engine) as _s:
                paused = _s.get(SystemSetting, "worker_paused")
                if paused and paused.value == "true":
                    paused.value = "false"
                    _s.add(paused)
                    _s.commit()
                    logger.info("[full_update] Worker 已自動恢復")
        except Exception as e:
            logger.error(f"[full_update] 恢復 Worker 失敗: {e}")
