from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from typing import Optional
from pydantic import BaseModel
from app.database import get_session
from app.models.core import Project, StageList, CardIndex, SystemSetting
from pathlib import Path
import asyncio
import re
import shutil
import uuid

router = APIRouter(tags=["github"])


# ==========================================
# GitHub Integration
# ==========================================
class GitHubTokenRequest(BaseModel):
    token: str


@router.post("/github/verify")
def verify_github_token(data: GitHubTokenRequest):
    """驗證 GitHub PAT 有效性"""
    import urllib.request
    req = urllib.request.Request(
        "https://api.github.com/user",
        headers={
            "Authorization": f"Bearer {data.token}",
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            import json as _json
            user = _json.loads(resp.read().decode("utf-8"))
            return {
                "ok": True,
                "login": user["login"],
                "name": user.get("name", ""),
                "avatar_url": user.get("avatar_url", ""),
            }
    except urllib.error.HTTPError:
        raise HTTPException(status_code=401, detail="GitHub Token 無效")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"無法連線 GitHub API: {e}")


@router.get("/github/status")
def get_github_status(session: Session = Depends(get_session)):
    """取得 GitHub 連線狀態"""
    setting = session.get(SystemSetting, "github_pat")
    if not setting or not setting.value:
        return {"connected": False}

    import urllib.request
    req = urllib.request.Request(
        "https://api.github.com/user",
        headers={
            "Authorization": f"Bearer {setting.value}",
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            import json as _json
            user = _json.loads(resp.read().decode("utf-8"))
            return {"connected": True, "login": user["login"], "name": user.get("name", "")}
    except Exception:
        return {"connected": False, "error": "Token 已失效"}


# --- GitHub: Parse URL ---
class GitHubParseUrlRequest(BaseModel):
    url: str

@router.post("/github/parse-url")
def parse_github_url(data: GitHubParseUrlRequest):
    """解析 GitHub URL，回傳 owner/repo/clone_url"""
    m = re.match(r"https?://github\.com/([^/]+)/([^/.\s]+?)(?:\.git)?/?$", data.url.strip())
    if not m:
        raise HTTPException(status_code=400, detail="無效的 GitHub URL 格式")
    owner, repo = m.group(1), m.group(2)
    return {
        "owner": owner,
        "repo": repo,
        "full_name": f"{owner}/{repo}",
        "clone_url": f"https://github.com/{owner}/{repo}.git",
        "suggested_name": repo,
    }


# --- GitHub: List Repos ---
@router.get("/github/repos")
def list_github_repos(
    page: int = 1,
    per_page: int = 30,
    search: str = "",
    session: Session = Depends(get_session),
):
    """列出使用者的 GitHub repos（需已儲存 PAT）"""
    setting = session.get(SystemSetting, "github_pat")
    if not setting or not setting.value:
        raise HTTPException(status_code=400, detail="尚未連線 GitHub，請先設定 PAT")

    import httpx

    headers = {
        "Authorization": f"Bearer {setting.value}",
        "Accept": "application/vnd.github+json",
    }

    try:
        if search.strip():
            # 使用 GitHub Search API
            resp = httpx.get(
                "https://api.github.com/search/repositories",
                params={"q": f"{search} user:@me fork:true", "per_page": per_page, "page": page},
                headers=headers,
                timeout=15,
            )
            resp.raise_for_status()
            items = resp.json().get("items", [])
        else:
            # 列出使用者所有 repos（含 org 的）
            resp = httpx.get(
                "https://api.github.com/user/repos",
                params={"sort": "updated", "per_page": per_page, "page": page, "affiliation": "owner,collaborator,organization_member"},
                headers=headers,
                timeout=15,
            )
            resp.raise_for_status()
            items = resp.json()

        return [
            {
                "full_name": r["full_name"],
                "name": r["name"],
                "clone_url": r["clone_url"],
                "description": r.get("description"),
                "private": r["private"],
                "default_branch": r.get("default_branch", "main"),
            }
            for r in items
        ]
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=f"GitHub API 錯誤: {e.response.text[:200]}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"無法連線 GitHub API: {e}")


# --- GitHub: Clone ---
class GitHubCloneRequest(BaseModel):
    repo_url: str
    destination: str
    project_name: str
    default_member_id: Optional[int] = None

# 背景 clone 任務狀態
_clone_tasks: dict = {}

@router.post("/github/clone")
async def clone_github_repo(data: GitHubCloneRequest, session: Session = Depends(get_session)):
    """Clone GitHub repo 並建立專案（背景執行）"""
    dest = Path(data.destination)
    if dest.exists():
        raise HTTPException(status_code=400, detail="目標路徑已存在")
    # 確保父目錄存在
    if not dest.parent.exists():
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"無法建立父目錄: {e}")

    # 注入 PAT（私有 repo 需要）
    clone_url = data.repo_url
    setting = session.get(SystemSetting, "github_pat")
    if setting and setting.value:
        clone_url = clone_url.replace("https://github.com/", f"https://{setting.value}@github.com/")

    task_id = str(uuid.uuid4())
    _clone_tasks[task_id] = {"status": "cloning", "message": "正在 clone...", "project_id": None}

    asyncio.create_task(_do_clone(
        task_id=task_id,
        clone_url=clone_url,
        destination=str(dest),
        project_name=data.project_name,
        default_member_id=data.default_member_id,
    ))

    return {"task_id": task_id, "status": "cloning"}


async def _do_clone(task_id: str, clone_url: str, destination: str, project_name: str, default_member_id: Optional[int]):
    """背景 clone 任務"""
    from app.core.ws_manager import broadcast_event
    from app.database import engine

    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "clone", "--depth", "1", clone_url, destination,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            err_msg = stderr.decode().strip()
            # 隱藏 PAT
            err_msg = re.sub(r"https://[^@]+@github\.com", "https://***@github.com", err_msg)
            _clone_tasks[task_id] = {"status": "error", "message": f"Clone 失敗: {err_msg}", "project_id": None}
            await broadcast_event("clone_progress", _clone_tasks[task_id] | {"task_id": task_id})
            return

        # Clone 成功，建立專案
        with Session(engine) as session:
            project_path = Path(destination)
            cards_dir = project_path / "cards"
            cards_dir.mkdir(exist_ok=True)

            project = Project(
                name=project_name,
                path=str(project_path),
                deploy_type="none",
                default_member_id=default_member_id,
            )
            session.add(project)
            session.commit()
            session.refresh(project)

            stages_config = [
                ("Backlog", False, "none", "none"),
                ("Scheduled", True, "delete", "none"),
                ("Planning", True, "none", "none"),
                ("Developing", True, "none", "none"),
                ("Verifying", True, "none", "none"),
                ("Done", False, "none", "none"),
                ("Aborted", False, "none", "none"),
            ]
            for idx, (name, is_ai, on_success, on_fail) in enumerate(stages_config):
                sl = StageList(
                    project_id=project.id,
                    name=name,
                    position=idx,
                    is_ai_stage=is_ai,
                    on_success_action=on_success,
                    on_fail_action=on_fail,
                )
                session.add(sl)
            session.commit()

            _clone_tasks[task_id] = {"status": "done", "message": "Clone 完成，專案已建立", "project_id": project.id}

        await broadcast_event("clone_progress", _clone_tasks[task_id] | {"task_id": task_id})

    except Exception as e:
        _clone_tasks[task_id] = {"status": "error", "message": str(e), "project_id": None}
        await broadcast_event("clone_progress", _clone_tasks[task_id] | {"task_id": task_id})


@router.get("/github/clone/{task_id}")
def get_clone_status(task_id: str):
    """查詢 clone 任務狀態"""
    task = _clone_tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="找不到此 clone 任務")
    return {"task_id": task_id, **task}


# --- Project Relocate ---
class ProjectRelocateRequest(BaseModel):
    new_path: str

@router.post("/projects/{project_id}/relocate", response_model=Project)
def relocate_project(project_id: int, data: ProjectRelocateRequest, session: Session = Depends(get_session)):
    """搬移專案目錄到新路徑"""
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="找不到專案")
    if project.is_system:
        raise HTTPException(status_code=403, detail="無法搬移系統專案")

    old_path = Path(project.path)
    new_path = Path(data.new_path)

    if not new_path.is_absolute():
        raise HTTPException(status_code=400, detail="請提供絕對路徑")
    if str(old_path) == str(new_path):
        raise HTTPException(status_code=400, detail="新路徑與目前相同")
    if new_path.exists():
        raise HTTPException(status_code=400, detail="目標路徑已存在")
    if not new_path.parent.exists():
        try:
            new_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"無法建立父目錄: {e}")

    # 檢查是否有執行中的任務
    running = session.exec(
        select(CardIndex).where(CardIndex.project_id == project_id, CardIndex.status == "running")
    ).first()
    if running:
        raise HTTPException(status_code=409, detail="有任務正在執行，請等待完成後再搬移")

    if old_path.exists():
        try:
            shutil.move(str(old_path), str(new_path))
        except PermissionError:
            raise HTTPException(status_code=400, detail="權限不足，無法搬移目錄")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"搬移失敗: {e}")

    project.path = str(new_path)
    session.add(project)
    session.commit()
    session.refresh(project)
    return project
