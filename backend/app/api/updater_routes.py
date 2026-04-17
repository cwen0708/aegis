from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel import Session, select
from typing import Optional
from pydantic import BaseModel
from app.database import get_session
from app.models.core import Project, SystemSetting, CronJob
from app.core import updater
from app.version import read_version
from pathlib import Path
import logging
import re
import subprocess

logger = logging.getLogger(__name__)

router = APIRouter(tags=["updater"])


# ==========================================
# Version SSOT API
# ==========================================
def _git_describe_tag() -> str:
    """取得當前最新的 git tag（權威版本標籤）。失敗回傳空字串。"""
    install_root = Path(__file__).resolve().parents[3]
    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0"],
            cwd=str(install_root),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.SubprocessError, OSError) as exc:
        logger.warning("[version] git describe 失敗: %s", exc)
    return ""


async def _latest_available_tag(session: Session, channel: str) -> str:
    """查詢 GitHub 上該 channel 的最新可用 tag。失敗回傳空字串。"""
    import httpx

    if channel == "stable":
        pattern = re.compile(r"^v\d+\.\d+\.\d+-stable$")
    else:
        pattern = re.compile(r"^v\d+\.\d+\.\d+(-dev\.\d+)?$")

    gh_headers = {"Accept": "application/vnd.github.v3+json"}
    pat_setting = session.get(SystemSetting, "github_pat")
    if pat_setting and pat_setting.value:
        gh_headers["Authorization"] = f"token {pat_setting.value}"

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://api.github.com/repos/cwen0708/aegis/tags",
                headers=gh_headers,
                timeout=10.0,
            )
            if resp.status_code != 200:
                return ""
            tags = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("[version] GitHub tags 查詢失敗: %s", exc)
        return ""

    filtered = [t["name"] for t in tags if pattern.match(t["name"])]
    if not filtered:
        return ""
    filtered.sort(key=updater.parse_version, reverse=True)
    return filtered[0]


@router.get("/version")
async def get_version(session: Session = Depends(get_session)):
    """版本資訊 SSOT 端點。

    回傳：
      current: backend/VERSION 檔案內容（運行中服務的版本）
      tag: git describe --tags --abbrev=0（實際部署的 git tag）
      channel: "stable" or "development"（依 SystemSetting.update_channel）
      latest: 該頻道 GitHub 上最新可用 tag
    """
    channel_setting = session.get(SystemSetting, "update_channel")
    channel = channel_setting.value if channel_setting else "development"
    if channel not in ("stable", "development"):
        channel = "development"

    return {
        "current": read_version(),
        "tag": _git_describe_tag(),
        "channel": channel,
        "latest": await _latest_available_tag(session, channel),
    }


# ==========================================
# System Update API
# ==========================================


class UpdateSettingsPayload(BaseModel):
    auto_update_enabled: Optional[bool] = None
    auto_update_time: Optional[str] = None
    update_keep_versions: Optional[int] = None
    update_channel: Optional[str] = None  # "development" | "stable"


class ApplyUpdatePayload(BaseModel):
    version: Optional[str] = None
    wait_timeout: int = 300


class RollbackPayload(BaseModel):
    version: Optional[str] = None


@router.get("/update/status")
async def get_update_status(session: Session = Depends(get_session)):
    """取得更新狀態"""
    state = updater.get_update_state()

    # 讀取更新設定
    auto_enabled = session.get(SystemSetting, "auto_update_enabled")
    auto_time = session.get(SystemSetting, "auto_update_time")
    keep_versions = session.get(SystemSetting, "update_keep_versions")
    channel = session.get(SystemSetting, "update_channel")

    return {
        "current_version": state.current_version,
        "latest_version": state.latest_version,
        "has_update": state.has_update,
        "is_updating": state.is_updating,
        "update_stage": state.stage,
        "progress": state.progress,
        "message": state.message,
        "error": state.error,
        "available_versions": state.available_versions,
        "is_deployed": updater.is_deployed_environment(),
        "auto_update_enabled": auto_enabled.value == "true" if auto_enabled else False,
        "auto_update_time": auto_time.value if auto_time else "03:00",
        "update_keep_versions": int(keep_versions.value) if keep_versions else 3,
        "update_channel": channel.value if channel else "development",
    }


class CheckUpdatePayload(BaseModel):
    channel: Optional[str] = None  # 若未指定則從 DB 讀取


@router.post("/update/check")
async def check_for_updates(payload: CheckUpdatePayload = None, session: Session = Depends(get_session)):
    """檢查是否有新版本（獨立查詢，不污染全域 _state）"""
    if payload and payload.channel:
        channel = payload.channel
    else:
        channel_setting = session.get(SystemSetting, "update_channel")
        channel = channel_setting.value if channel_setting else "development"

    # 獨立查詢 GitHub，避免並行 check 互相覆蓋全域 _state
    try:
        import httpx

        current = updater.get_current_version()

        # 使用 GitHub PAT 避免 rate limit（未認證 60/hr，認證 5000/hr）
        gh_headers = {"Accept": "application/vnd.github.v3+json"}
        pat_setting = session.get(SystemSetting, "github_pat")
        if pat_setting and pat_setting.value:
            gh_headers["Authorization"] = f"token {pat_setting.value}"

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://api.github.com/repos/cwen0708/aegis/tags",
                headers=gh_headers,
                timeout=30.0
            )
            if resp.status_code != 200:
                raise Exception(f"GitHub API {resp.status_code}")
            tags = resp.json()

        if channel == "stable":
            tag_pattern = re.compile(r"^v\d+\.\d+\.\d+-stable$")
            channel_name = "穩定版"
        else:
            tag_pattern = re.compile(r"^v\d+\.\d+\.\d+(-dev\.\d+)?$")
            channel_name = "開發版"

        filtered = [t["name"] for t in tags if tag_pattern.match(t["name"])]

        if not filtered:
            return {
                "current_version": current, "latest_version": current,
                "has_update": False, "available_versions": [],
                "message": f"已是最新{channel_name}", "error": "", "channel": channel,
            }

        filtered.sort(key=updater.parse_version, reverse=True)
        latest = filtered[0].lstrip("v").replace("-stable", "")
        has_update = updater.is_newer_version(latest, current)

        return {
            "current_version": current,
            "latest_version": latest,
            "has_update": has_update,
            "available_versions": filtered[:10],
            "message": f"發現新{channel_name} {latest}" if has_update else f"已是最新{channel_name}",
            "error": "",
            "channel": channel,
        }
    except Exception as e:
        return {
            "current_version": updater.get_current_version(),
            "latest_version": "", "has_update": False,
            "available_versions": [], "message": "", "error": str(e),
            "channel": channel,
        }


@router.get("/update/versions")
async def list_versions():
    """列出版本歷史（優先從 git tags，fallback releases 目錄）"""
    current = updater.get_current_version()

    # 方法 1：從 git tags 取（適用 git 架構）
    versions = []
    try:
        import subprocess
        install_root = Path(__file__).parent.parent.parent.parent
        result = subprocess.run(
            ["git", "tag", "-l", "v*", "--sort=-v:refname"],
            cwd=str(install_root),
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            for tag in result.stdout.strip().split("\n"):
                tag = tag.strip()
                if tag:
                    # 取 tag 的日期和 commit message
                    info = subprocess.run(
                        ["git", "log", "-1", "--format=%ai|%s", tag],
                        cwd=str(install_root),
                        capture_output=True, text=True, timeout=5
                    )
                    date_str, title = "", tag
                    if info.returncode == 0 and "|" in info.stdout:
                        parts = info.stdout.strip().split("|", 1)
                        date_str = parts[0].strip()
                        title = parts[1].strip() if len(parts) > 1 else tag

                    versions.append({
                        "tag": tag.lstrip("v"),
                        "title": title,
                        "date": date_str,
                    })
            if versions:
                return {"versions": versions[:30], "current": current}
    except Exception:
        pass

    # 方法 2：從 releases 目錄取（適用 symlink 架構）
    if updater.is_deployed_environment():
        paths = updater.get_deployment_paths()
        releases_dir = paths["releases"]
        if releases_dir and releases_dir.exists():
            dir_versions = sorted(
                [d.name for d in releases_dir.iterdir() if d.is_dir()],
                key=updater.parse_version,
                reverse=True
            )
            versions = [{"tag": v, "title": v, "date": ""} for v in dir_versions]

    return {"versions": versions[:30], "current": current}


@router.post("/update/download")
async def download_update(version: Optional[str] = None):
    """下載指定版本"""
    if not updater.is_deployed_environment():
        raise HTTPException(status_code=400, detail="本地開發環境不支援熱更新")

    state = updater.get_update_state()
    target_version = version or state.latest_version

    if not target_version:
        raise HTTPException(status_code=400, detail="未指定版本且無可用更新")

    success = await updater.download_version(target_version)
    return {
        "ok": success,
        "version": target_version,
        "message": state.message,
        "error": state.error,
    }


@router.post("/update/build")
async def build_update(version: str):
    """建構指定版本"""
    if not updater.is_deployed_environment():
        raise HTTPException(status_code=400, detail="本地開發環境不支援熱更新")

    success = await updater.build_version(version)
    state = updater.get_update_state()
    return {
        "ok": success,
        "version": version,
        "message": state.message,
        "error": state.error,
    }


@router.post("/update/apply")
async def apply_update(payload: ApplyUpdatePayload, request: Request, session: Session = Depends(get_session)):
    """套用更新（背景執行，立即回應）。需要 admin token 或 AEGIS_DEPLOY_TOKEN。"""
    import asyncio, os
    from app.core.auth import verify_session_token, decode_session_token

    # 認證：admin token 或 deploy token
    auth_header = request.headers.get("authorization", "")
    token = auth_header.replace("Bearer ", "") if auth_header.startswith("Bearer ") else ""
    deploy_token = os.getenv("AEGIS_DEPLOY_TOKEN", "")

    is_admin = False
    if token and verify_session_token(token):
        payload_data = decode_session_token(token)
        is_admin = payload_data and payload_data.get("type") == "admin"
    is_deploy = deploy_token and token == deploy_token

    # localhost 也放行（內部呼叫）
    client_host = request.client.host if request.client else ""
    real_ip = request.headers.get("x-real-ip", "")
    is_local = client_host in ("127.0.0.1", "::1") and not real_ip

    if not (is_admin or is_deploy or is_local):
        raise HTTPException(status_code=403, detail="需要管理員權限或部署 Token")

    if not updater.is_deployed_environment():
        raise HTTPException(status_code=400, detail="本地開發環境不支援熱更新")

    # 檢查是否已在更新中
    state = updater.get_update_state()
    if state.is_updating:
        return {
            "ok": False,
            "version": state.current_version,
            "message": "已有更新正在進行中",
            "error": "",
        }

    # 背景執行完整更新流程，API 立即回應
    asyncio.create_task(updater.full_update(
        version=payload.version,
        wait_timeout=payload.wait_timeout
    ))

    return {
        "ok": True,
        "version": payload.version or "latest",
        "message": "更新已觸發，請透過 /update/status 查詢進度",
        "error": "",
    }


@router.post("/update/rollback")
async def rollback_update(payload: RollbackPayload):
    """回滾到指定版本"""
    if not updater.is_deployed_environment():
        raise HTTPException(status_code=400, detail="本地開發環境不支援回滾")

    success = await updater.rollback(payload.version)
    state = updater.get_update_state()
    return {
        "ok": success,
        "version": state.current_version,
        "message": state.message,
        "error": state.error,
    }


@router.put("/update/settings")
async def update_update_settings(payload: UpdateSettingsPayload, session: Session = Depends(get_session)):
    """更新自動更新設定（同時同步 CronJob）"""
    if payload.auto_update_enabled is not None:
        setting = session.get(SystemSetting, "auto_update_enabled")
        if setting:
            setting.value = "true" if payload.auto_update_enabled else "false"
        else:
            setting = SystemSetting(key="auto_update_enabled", value="true" if payload.auto_update_enabled else "false")
        session.add(setting)

    if payload.auto_update_time is not None:
        setting = session.get(SystemSetting, "auto_update_time")
        if setting:
            setting.value = payload.auto_update_time
        else:
            setting = SystemSetting(key="auto_update_time", value=payload.auto_update_time)
        session.add(setting)

    if payload.update_keep_versions is not None:
        setting = session.get(SystemSetting, "update_keep_versions")
        if setting:
            setting.value = str(payload.update_keep_versions)
        else:
            setting = SystemSetting(key="update_keep_versions", value=str(payload.update_keep_versions))
        session.add(setting)

    if payload.update_channel is not None:
        # 驗證頻道值
        if payload.update_channel not in ("development", "stable"):
            raise HTTPException(status_code=400, detail="無效的更新頻道")
        setting = session.get(SystemSetting, "update_channel")
        if setting:
            setting.value = payload.update_channel
        else:
            setting = SystemSetting(key="update_channel", value=payload.update_channel)
        session.add(setting)

    # 同步更新 CronJob
    aegis_project = session.exec(
        select(Project).where(Project.is_system == True)
    ).first()

    if aegis_project:
        update_job = session.exec(
            select(CronJob).where(
                CronJob.project_id == aegis_project.id,
                CronJob.name == "系統更新檢查"
            )
        ).first()

        if update_job:
            if payload.auto_update_enabled is not None:
                update_job.is_enabled = payload.auto_update_enabled

            if payload.auto_update_time is not None:
                hour, minute = map(int, payload.auto_update_time.split(":"))
                update_job.cron_expression = f"{minute} {hour} * * *"
                # 重新計算下次執行時間（用系統時區）
                from app.core.cron_poller import _calculate_next_time, _get_system_timezone
                tz_name = _get_system_timezone(session)
                next_time = _calculate_next_time(update_job.cron_expression, tz_name)
                if next_time:
                    update_job.next_scheduled_at = next_time

            session.add(update_job)

    session.commit()
    return {"ok": True}
