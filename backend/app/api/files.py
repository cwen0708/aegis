"""
Aegis File Browser + Git API
專案檔案瀏覽與 Git 整合
"""
import os
import subprocess
import mimetypes
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Header
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlmodel import Session

from app.database import get_session
from app.models.core import Project
from app.core.auth import verify_session_token

router = APIRouter(tags=["files"])

# 排除的目錄/檔案
EXCLUDED_NAMES = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    "dist", ".next", ".nuxt", ".cache", ".DS_Store",
    "Thumbs.db", ".env", ".env.local",
}

MAX_FILE_SIZE = 1 * 1024 * 1024  # 1MB

# 支援預覽的圖片副檔名
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".bmp"}


# ==========================================
# 工具函式
# ==========================================

def _get_project(project_id: int, session: Session) -> Project:
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _resolve_safe_path(project_path: str, relative_path: str) -> Path:
    """解析路徑並防止路徑穿越攻擊"""
    base = Path(project_path).resolve()
    if not relative_path or relative_path in (".", "/"):
        return base

    target = (base / relative_path).resolve()

    # 確認目標路徑仍在專案目錄下
    try:
        target.relative_to(base)
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied: path traversal")

    # 防止 symlink 指向外部
    real_target = Path(os.path.realpath(target))
    real_base = Path(os.path.realpath(base))
    try:
        real_target.relative_to(real_base)
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied: symlink escape")

    return target


def _is_text_file(file_path: Path) -> bool:
    """判斷是否為文字檔案"""
    mime, _ = mimetypes.guess_type(str(file_path))
    if mime and mime.startswith("text/"):
        return True
    # 常見程式碼副檔名
    text_exts = {
        ".py", ".js", ".ts", ".tsx", ".jsx", ".vue", ".svelte",
        ".html", ".css", ".scss", ".less", ".sass",
        ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg",
        ".md", ".txt", ".rst", ".csv", ".tsv",
        ".sh", ".bash", ".zsh", ".fish", ".bat", ".ps1",
        ".sql", ".graphql", ".gql",
        ".xml", ".svg", ".env", ".gitignore", ".dockerignore",
        ".rs", ".go", ".java", ".kt", ".swift", ".cs", ".rb",
        ".php", ".lua", ".r", ".R", ".dart", ".ex", ".exs",
        ".c", ".h", ".cpp", ".hpp", ".cc",
        ".lock", ".editorconfig", ".prettierrc",
        ".dockerfile", ".tf", ".hcl",
    }
    return file_path.suffix.lower() in text_exts


def _run_git(project_path: str, args: list[str], timeout: int = 10) -> tuple[bool, str]:
    """執行 git 命令，回傳 (success, output)"""
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode == 0, result.stdout.strip()
    except subprocess.TimeoutExpired:
        return False, "Git command timed out"
    except FileNotFoundError:
        return False, "Git not installed"


def _is_git_repo(project_path: str) -> bool:
    ok, _ = _run_git(project_path, ["rev-parse", "--is-inside-work-tree"])
    return ok


# ==========================================
# 檔案瀏覽 API
# ==========================================

class FileEntry(BaseModel):
    name: str
    path: str        # 相對於 project.path
    type: str        # "file" | "directory"
    size: Optional[int] = None
    modified: Optional[str] = None


def _is_authenticated(authorization: str | None) -> bool:
    """從 Authorization header 檢查是否已登入

    - 有帶有效 token → True
    - 沒帶 token 但系統沒設密碼 → True（開放環境）
    - 沒帶 token 且系統有密碼 → False
    """
    if authorization and authorization.startswith("Bearer "):
        if verify_session_token(authorization[7:]):
            return True
    # 沒有有效 token：檢查系統是否有設密碼
    try:
        from sqlmodel import Session as SqlSession
        from app.database import engine
        from app.models.core import SystemSetting
        with SqlSession(engine) as s:
            pwd = s.get(SystemSetting, "admin_password")
            if not pwd or not pwd.value:
                return True  # 沒設密碼，視為開放環境
    except Exception:
        pass
    return False


@router.get("/projects/{project_id}/files")
def list_files(
    project_id: int,
    path: str = Query("", description="相對路徑，空字串表示根目錄"),
    session: Session = Depends(get_session),
    authorization: str | None = Header(None),
):
    """列出目錄內容（單層，lazy load）

    未登入：隱藏所有 dot 開頭的檔案/目錄
    已登入：只隱藏 EXCLUDED_NAMES（.git, node_modules 等）
    """
    project = _get_project(project_id, session)
    target = _resolve_safe_path(project.path, path)

    if not target.exists():
        raise HTTPException(status_code=404, detail="Directory not found")
    if not target.is_dir():
        raise HTTPException(status_code=400, detail="Not a directory")

    authenticated = _is_authenticated(authorization)
    base = Path(project.path).resolve()
    entries: list[dict] = []

    try:
        for item in sorted(target.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            if item.name in EXCLUDED_NAMES:
                continue
            # 未登入：隱藏所有 dot 檔案/目錄
            # 已登入：放行 dot 檔案（但仍排除 EXCLUDED_NAMES）
            if item.name.startswith("."):
                if not authenticated:
                    continue

            try:
                stat = item.stat()
                rel = str(item.resolve().relative_to(base)).replace("\\", "/")
                entries.append({
                    "name": item.name,
                    "path": rel,
                    "type": "directory" if item.is_dir() else "file",
                    "size": stat.st_size if item.is_file() else None,
                    "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                })
            except (PermissionError, OSError):
                continue
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied")

    return {"entries": entries, "path": path or ".", "is_git": _is_git_repo(project.path)}


@router.get("/projects/{project_id}/files/content")
def read_file_content(
    project_id: int,
    path: str = Query(..., description="檔案相對路徑"),
    session: Session = Depends(get_session),
    authorization: str | None = Header(None),
):
    """讀取檔案內容"""
    project = _get_project(project_id, session)
    target = _resolve_safe_path(project.path, path)

    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")
    if not target.is_file():
        raise HTTPException(status_code=400, detail="Not a file")

    # 未登入時禁止讀取 dot 檔案/路徑中包含 dot 目錄的檔案
    if not _is_authenticated(authorization):
        parts = Path(path).parts
        if any(p.startswith(".") for p in parts):
            raise HTTPException(status_code=403, detail="Authentication required to access hidden files")

    size = target.stat().st_size

    # 二進位檔案
    if not _is_text_file(target):
        return {
            "path": path,
            "content": None,
            "size": size,
            "binary": True,
            "truncated": False,
        }

    # 文字檔案
    truncated = size > MAX_FILE_SIZE
    try:
        with open(target, "r", encoding="utf-8", errors="replace") as f:
            content = f.read(MAX_FILE_SIZE)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cannot read file: {e}")

    return {
        "path": path,
        "content": content,
        "size": size,
        "binary": False,
        "truncated": truncated,
        "language": _guess_language(target),
    }


@router.get("/projects/{project_id}/files/raw")
def raw_file(
    project_id: int,
    path: str = Query(..., description="檔案相對路徑"),
    session: Session = Depends(get_session),
):
    """提供原始檔案（圖片預覽用）"""
    project = _get_project(project_id, session)
    target = _resolve_safe_path(project.path, path)

    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    if target.suffix.lower() not in IMAGE_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Only image files supported")

    mime, _ = mimetypes.guess_type(str(target))
    return FileResponse(target, media_type=mime or "application/octet-stream")


def _guess_language(file_path: Path) -> str:
    """猜測程式語言（前端高亮用）"""
    ext_map = {
        ".py": "python", ".js": "javascript", ".ts": "typescript",
        ".tsx": "tsx", ".jsx": "jsx", ".vue": "vue",
        ".html": "html", ".css": "css", ".scss": "scss",
        ".json": "json", ".yaml": "yaml", ".yml": "yaml",
        ".md": "markdown", ".sql": "sql", ".sh": "bash",
        ".rs": "rust", ".go": "go", ".java": "java",
        ".cs": "csharp", ".rb": "ruby", ".php": "php",
        ".swift": "swift", ".kt": "kotlin", ".dart": "dart",
        ".toml": "toml", ".xml": "xml", ".svg": "xml",
        ".c": "c", ".h": "c", ".cpp": "cpp", ".hpp": "cpp",
        ".dockerfile": "dockerfile", ".graphql": "graphql",
    }
    return ext_map.get(file_path.suffix.lower(), "text")


# ==========================================
# Git API
# ==========================================

@router.get("/projects/{project_id}/git/status")
def git_status(
    project_id: int,
    session: Session = Depends(get_session),
):
    """取得 Git 狀態"""
    project = _get_project(project_id, session)

    if not _is_git_repo(project.path):
        return {"is_git": False}

    # Branch
    ok, branch = _run_git(project.path, ["rev-parse", "--abbrev-ref", "HEAD"])
    if not ok:
        branch = "unknown"

    # Ahead/behind
    ahead, behind = 0, 0
    ok, tracking = _run_git(project.path, ["rev-parse", "--abbrev-ref", "@{upstream}"])
    if ok:
        ok, counts = _run_git(project.path, ["rev-list", "--left-right", "--count", f"HEAD...{tracking}"])
        if ok and "\t" in counts:
            parts = counts.split("\t")
            ahead, behind = int(parts[0]), int(parts[1])

    # Status
    ok, status_output = _run_git(project.path, ["status", "--porcelain", "-u"])
    staged, modified, untracked = [], [], []
    if ok:
        for line in status_output.splitlines():
            if len(line) < 4:
                continue
            x, y = line[0], line[1]
            fname = line[3:]
            if x in ("A", "M", "D", "R"):
                staged.append(fname)
            if y == "M":
                modified.append(fname)
            elif y == "?":
                untracked.append(fname)

    return {
        "is_git": True,
        "branch": branch,
        "ahead": ahead,
        "behind": behind,
        "staged": staged,
        "modified": modified,
        "untracked": untracked,
        "is_clean": len(staged) == 0 and len(modified) == 0 and len(untracked) == 0,
    }


@router.get("/projects/{project_id}/git/log")
def git_log(
    project_id: int,
    limit: int = Query(20, ge=1, le=100),
    session: Session = Depends(get_session),
):
    """取得 commit 歷史"""
    project = _get_project(project_id, session)

    if not _is_git_repo(project.path):
        return {"is_git": False, "commits": []}

    fmt = "%H%n%h%n%s%n%an%n%aI%n---"
    ok, output = _run_git(project.path, [
        "log", f"--max-count={limit}", f"--format={fmt}",
    ])

    if not ok:
        return {"is_git": True, "commits": []}

    commits = []
    lines = output.split("\n---\n")
    for block in lines:
        parts = block.strip().split("\n")
        if len(parts) < 5:
            continue
        commits.append({
            "sha_full": parts[0],
            "sha": parts[1],
            "message": parts[2],
            "author": parts[3],
            "date": parts[4],
        })

    return {"is_git": True, "commits": commits}


@router.get("/projects/{project_id}/git/diff")
def git_diff(
    project_id: int,
    file: Optional[str] = Query(None, description="特定檔案的 diff"),
    staged: bool = Query(False, description="顯示 staged diff"),
    session: Session = Depends(get_session),
):
    """取得 diff 內容"""
    project = _get_project(project_id, session)

    if not _is_git_repo(project.path):
        return {"is_git": False, "diff": ""}

    args = ["diff"]
    if staged:
        args.append("--cached")
    if file:
        # 安全檢查
        _resolve_safe_path(project.path, file)
        args.extend(["--", file])

    ok, output = _run_git(project.path, args, timeout=15)

    return {
        "is_git": True,
        "diff": output if ok else "",
        "file": file,
        "staged": staged,
    }


@router.post("/projects/{project_id}/git/fetch")
def git_fetch(
    project_id: int,
    session: Session = Depends(get_session),
):
    """執行 git fetch 更新遠端追蹤分支"""
    project = _get_project(project_id, session)

    if not _is_git_repo(project.path):
        raise HTTPException(status_code=400, detail="Not a git repository")

    ok, output = _run_git(project.path, ["fetch", "--prune"], timeout=30)
    if not ok:
        return {"ok": False, "error": output}

    # 重新取得 ahead/behind
    ahead, behind = 0, 0
    ok2, tracking = _run_git(project.path, ["rev-parse", "--abbrev-ref", "@{upstream}"])
    if ok2:
        ok3, counts = _run_git(project.path, ["rev-list", "--left-right", "--count", f"HEAD...{tracking}"])
        if ok3 and "\t" in counts:
            parts = counts.split("\t")
            ahead, behind = int(parts[0]), int(parts[1])

    return {"ok": True, "ahead": ahead, "behind": behind}


def _git_commit_info(repo_path: str) -> dict:
    """取得指定路徑的 HEAD commit 資訊"""
    if not _is_git_repo(repo_path):
        return {"exists": False}

    ok, sha = _run_git(repo_path, ["rev-parse", "--short", "HEAD"])
    ok2, sha_full = _run_git(repo_path, ["rev-parse", "HEAD"])
    ok3, msg = _run_git(repo_path, ["log", "-1", "--format=%s"])
    ok4, date = _run_git(repo_path, ["log", "-1", "--format=%ci"])
    ok5, branch = _run_git(repo_path, ["rev-parse", "--abbrev-ref", "HEAD"])

    return {
        "exists": True,
        "sha": sha if ok else "",
        "sha_full": sha_full if ok2 else "",
        "message": msg if ok3 else "",
        "date": date if ok4 else "",
        "branch": branch if ok5 else "",
    }


@router.get("/projects/{project_id}/git/overview")
def git_overview(
    project_id: int,
    session: Session = Depends(get_session),
):
    """三環境版本比較：開發版 / 運行版 / 遠端"""
    from app.core.task_workspace import _INSTALL_ROOT

    project = _get_project(project_id, session)
    dev_path = project.path
    runtime_path = str(_INSTALL_ROOT)

    # 只有 AEGIS 系統專案且 dev/runtime 路徑不同時才顯示運行版
    is_separated = project.is_system and os.path.realpath(dev_path) != os.path.realpath(runtime_path)

    # 1. 開發版（dev dir = project.path）
    dev = _git_commit_info(dev_path)
    dev["label"] = "開發版"

    # 2. 運行版（.local/aegis）— 只在分離架構時顯示
    if is_separated:
        runtime = _git_commit_info(runtime_path)
        runtime["label"] = "運行版"
    else:
        runtime = {"exists": False, "label": "運行版"}

    # 3. 遠端（origin/main）
    origin: dict = {"exists": False, "label": "遠端"}
    if _is_git_repo(dev_path):
        ok, sha = _run_git(dev_path, ["rev-parse", "--short", "origin/main"])
        ok2, sha_full = _run_git(dev_path, ["rev-parse", "origin/main"])
        ok3, msg = _run_git(dev_path, ["log", "-1", "--format=%s", "origin/main"])
        ok4, date = _run_git(dev_path, ["log", "-1", "--format=%ci", "origin/main"])
        ok5, url = _run_git(dev_path, ["remote", "get-url", "origin"])
        # 清理 PAT from URL
        if ok5 and "@" in url:
            url = "https://" + url.split("@")[-1]
        origin = {
            "exists": ok,
            "label": "遠端",
            "sha": sha if ok else "",
            "sha_full": sha_full if ok2 else "",
            "message": msg if ok3 else "",
            "date": date if ok4 else "",
            "url": url if ok5 else "",
        }

    # 4. 比較差異
    dev_vs_runtime = 0
    dev_vs_origin = 0
    runtime_vs_origin = 0

    if dev.get("sha_full") and runtime.get("sha_full") and _is_git_repo(dev_path):
        ok, count = _run_git(dev_path, ["rev-list", "--count", f"{runtime['sha_full']}..HEAD"])
        dev_vs_runtime = int(count) if ok and count.isdigit() else 0

    if dev.get("sha_full") and origin.get("sha_full") and _is_git_repo(dev_path):
        ok, count = _run_git(dev_path, ["rev-list", "--count", f"origin/main..HEAD"])
        dev_vs_origin = int(count) if ok and count.isdigit() else 0

    if runtime.get("sha_full") and origin.get("sha_full") and _is_git_repo(runtime_path):
        ok, count = _run_git(runtime_path, ["rev-list", "--count", f"origin/main..HEAD"])
        runtime_vs_origin = int(count) if ok and count.isdigit() else 0

    # 同步狀態
    all_synced = (dev.get("sha_full") == runtime.get("sha_full") == origin.get("sha_full"))

    # 5. 三條線的 commit 歷史
    # 取 dev 的最近 15 筆 commit（涵蓋所有環境的 HEAD）
    graph_commits = []
    if _is_git_repo(dev_path):
        ok, log_out = _run_git(dev_path, [
            "log", "--format=%H|%h|%s|%ci", "-15", "HEAD"
        ])
        if ok:
            for line in log_out.splitlines():
                parts = line.split("|", 3)
                if len(parts) == 4:
                    graph_commits.append({
                        "sha_full": parts[0], "sha": parts[1],
                        "message": parts[2], "date": parts[3],
                    })

    # 標記每個 commit 屬於哪些環境
    dev_sha = dev.get("sha_full", "")
    runtime_sha = runtime.get("sha_full", "")
    origin_sha = origin.get("sha_full", "")

    # 找出每個環境的 HEAD 在 graph_commits 中的 index
    dev_idx = -1
    runtime_idx = -1
    origin_idx = -1
    for i, c in enumerate(graph_commits):
        if c["sha_full"] == dev_sha:
            dev_idx = i
        if c["sha_full"] == runtime_sha:
            runtime_idx = i
        if c["sha_full"] == origin_sha:
            origin_idx = i

    # 如果 runtime 或 origin 不在 dev 歷史中（真正分叉），嘗試補充
    if runtime_idx == -1 and runtime_sha and is_separated and _is_git_repo(runtime_path):
        ok_r, r_log = _run_git(runtime_path, ["log", "--format=%H|%h|%s|%ci", "-1", "HEAD"])
        if ok_r:
            parts = r_log.split("|", 3)
            if len(parts) == 4:
                runtime_idx = len(graph_commits)
                graph_commits.append({"sha_full": parts[0], "sha": parts[1], "message": parts[2], "date": parts[3]})

    return {
        "dev": dev,
        "runtime": runtime,
        "origin": origin,
        "dev_ahead_of_runtime": dev_vs_runtime,
        "dev_ahead_of_origin": dev_vs_origin,
        "runtime_ahead_of_origin": runtime_vs_origin,
        "all_synced": all_synced,
        "graph": {
            "commits": list(reversed(graph_commits)),  # 舊→新
            "dev_idx": len(graph_commits) - 1 - dev_idx if dev_idx >= 0 else -1,
            "runtime_idx": len(graph_commits) - 1 - runtime_idx if runtime_idx >= 0 else -1,
            "origin_idx": len(graph_commits) - 1 - origin_idx if origin_idx >= 0 else -1,
        },
    }


@router.post("/projects/{project_id}/git/push")
def git_push(
    project_id: int,
    session: Session = Depends(get_session),
):
    """推送本地 commit 到遠端（需要 push 權限）"""
    project = _get_project(project_id, session)

    if not _is_git_repo(project.path):
        raise HTTPException(status_code=400, detail="Not a git repository")

    ok, output = _run_git(project.path, ["push", "origin", "main"], timeout=30)
    if not ok:
        return {"ok": False, "error": output}

    return {"ok": True, "message": output or "Push successful"}


@router.post("/projects/{project_id}/git/pull")
def git_pull(
    project_id: int,
    session: Session = Depends(get_session),
):
    """從遠端拉取最新 commit（fast-forward only）"""
    project = _get_project(project_id, session)

    if not _is_git_repo(project.path):
        raise HTTPException(status_code=400, detail="Not a git repository")

    # fetch first
    _run_git(project.path, ["fetch", "origin"], timeout=30)

    # try merge (ff-only to be safe)
    ok, output = _run_git(project.path, ["merge", "--ff-only", "origin/main"], timeout=30)
    if not ok:
        return {"ok": False, "error": f"Fast-forward 失敗（可能有本地 commit 衝突）: {output}"}

    return {"ok": True, "message": output or "Pull successful"}


@router.post("/projects/{project_id}/git/reset")
def git_reset(
    project_id: int,
    session: Session = Depends(get_session),
):
    """放棄所有未 commit 的改動"""
    project = _get_project(project_id, session)

    if not _is_git_repo(project.path):
        raise HTTPException(status_code=400, detail="Not a git repository")

    _run_git(project.path, ["checkout", "--", "."])
    _run_git(project.path, ["clean", "-fd"])

    return {"ok": True, "message": "已放棄所有未 commit 的改動"}


@router.post("/projects/{project_id}/git/deploy-to-runtime")
def git_deploy_to_runtime(
    project_id: int,
    data: dict = None,
    session: Session = Depends(get_session),
):
    """建立 AI 卡片，將開發版或遠端版部署到運行環境"""
    from app.core.task_workspace import _INSTALL_ROOT
    from app.models.core import StageList, Member
    from app.core.card_file import CardData, card_file_path, write_card, next_card_id
    from app.core.card_sync import sync_card_to_index
    from sqlmodel import select

    project = _get_project(project_id, session)
    source = (data or {}).get("source", "dev")  # "dev" or "origin"
    runtime_path = str(_INSTALL_ROOT)
    dev_path = project.path

    if os.path.realpath(dev_path) == os.path.realpath(runtime_path):
        return {"ok": False, "error": "開發環境和運行環境相同，無需部署"}

    # 找愛吉絲（系統管理員）的收件匣
    aegis_member = session.exec(select(Member).where(Member.slug == "aegis")).first()
    target_list = None
    if aegis_member:
        target_list = session.exec(
            select(StageList).where(
                StageList.project_id == project_id,
                StageList.member_id == aegis_member.id,
            )
        ).first()

    if not target_list:
        # fallback: 第一個 AI stage
        target_list = session.exec(
            select(StageList).where(
                StageList.project_id == project_id,
                StageList.is_ai_stage == True,
            ).order_by(StageList.position)
        ).first()

    if not target_list:
        return {"ok": False, "error": "找不到可用的任務列表"}

    if source == "dev":
        prompt = (
            f"請將開發目錄 ({dev_path}) 的最新程式碼部署到運行環境 ({runtime_path})。\n\n"
            "執行步驟：\n"
            f"1. cp -r {dev_path}/backend/app/ {runtime_path}/backend/app/\n"
            f"2. cp {dev_path}/backend/worker.py {runtime_path}/backend/worker.py\n"
            f"3. cd {dev_path}/frontend && pnpm build && cp -r dist/ {runtime_path}/frontend/dist/\n"
            "4. sudo systemctl restart aegis && sudo systemctl restart aegis-worker\n"
            "5. sleep 3 && curl -s http://127.0.0.1:8899/api/v1/runner/status\n"
        )
        title = "部署開發版到運行環境"
    else:
        prompt = (
            f"請將運行環境 ({runtime_path}) 更新到遠端最新版本。\n\n"
            "執行步驟：\n"
            f"1. cd {runtime_path} && git fetch origin && git reset --hard origin/main\n"
            f"2. cd backend && ./venv/bin/pip install -r requirements.txt -q\n"
            "3. 下載最新前端 dist（從 GitHub Release）\n"
            "4. sudo systemctl restart aegis && sudo systemctl restart aegis-worker\n"
            "5. sleep 3 && curl -s http://127.0.0.1:8899/api/v1/runner/status\n"
        )
        title = "更新運行環境到最新遠端版本"

    new_id = next_card_id(session)
    card_data = CardData(
        id=new_id,
        title=title,
        status="idle",
        list_id=target_list.id,
        content=prompt,
    )

    file_path = card_file_path(project.path, new_id)
    write_card(file_path, card_data)
    sync_card_to_index(session, card_data, project_id, str(file_path))
    session.commit()

    # 觸發
    from app.core.card_index import update_card_status
    update_card_status(new_id, "pending")

    return {"ok": True, "card_id": new_id, "title": title}


@router.post("/projects/{project_id}/git/pull-task")
def git_pull_task(
    project_id: int,
    session: Session = Depends(get_session),
):
    """建立 AI 卡片執行 git pull，自動處理衝突"""
    from app.models.core import StageList, Card, Project
    from app.core.card_file import CardData, card_file_path, write_card, next_card_id
    from app.core.card_sync import sync_card_to_index
    from sqlmodel import select
    from sqlalchemy import func as sa_func

    project = _get_project(project_id, session)

    if not _is_git_repo(project.path):
        raise HTTPException(status_code=400, detail="Not a git repository")

    # 找到第一個 AI 處理階段（Scheduled 或 Processing）
    stages = session.exec(
        select(StageList)
        .where(StageList.project_id == project_id)
        .where(StageList.is_ai_stage == True)
        .order_by(StageList.position)
    ).all()

    if not stages:
        raise HTTPException(status_code=400, detail="No AI stage found for this project")

    target_stage = stages[0]

    # 建立卡片
    new_id = next_card_id(session)
    old_max_id = session.exec(select(sa_func.max(Card.id))).one()
    if old_max_id is not None:
        new_id = max(new_id, old_max_id + 1)

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)

    card_data = CardData(
        id=new_id,
        list_id=target_stage.id,
        title="Git Pull — 拉取遠端更新",
        description="自動拉取遠端變更並處理衝突",
        content=(
            "請執行以下操作：\n\n"
            "1. 執行 `git pull` 拉取遠端最新程式碼\n"
            "2. 如果有合併衝突，請逐一解決衝突：\n"
            "   - 查看衝突檔案\n"
            "   - 根據程式碼邏輯選擇合理的合併方式\n"
            "   - 保留雙方有意義的變更\n"
            "3. 確認合併完成後，執行 `git status` 確認工作目錄乾淨\n"
            "4. 回報拉取結果（更新了哪些檔案、是否有衝突及如何解決）"
        ),
        status="idle",
        tags=[],
        created_at=now,
        updated_at=now,
    )

    fpath = card_file_path(project.path, new_id)
    fpath.parent.mkdir(parents=True, exist_ok=True)
    write_card(fpath, card_data)
    sync_card_to_index(session, card_data, project_id=project.id, file_path=str(fpath))

    # Dual-write
    orm_card = Card(
        id=new_id, list_id=target_stage.id,
        title=card_data.title, description=card_data.description,
        status="idle", created_at=now, updated_at=now,
    )
    session.add(orm_card)
    session.commit()

    # 觸發
    orm_card.status = "pending"
    orm_card.updated_at = now
    session.add(orm_card)

    from app.core.card_file import read_card_md
    cd = read_card_md(fpath)
    cd.status = "pending"
    cd.updated_at = now
    write_card(fpath, cd)
    sync_card_to_index(session, cd, project_id=project.id, file_path=str(fpath))

    session.commit()

    return {
        "ok": True,
        "card_id": new_id,
        "stage": target_stage.name,
        "message": f"已建立拉取任務 #{new_id}，AI 將自動執行 git pull",
    }


@router.get("/projects/{project_id}/git/branches")
def git_branches(
    project_id: int,
    session: Session = Depends(get_session),
):
    """取得分支列表"""
    project = _get_project(project_id, session)

    if not _is_git_repo(project.path):
        return {"is_git": False, "branches": []}

    ok, current = _run_git(project.path, ["rev-parse", "--abbrev-ref", "HEAD"])
    current_branch = current if ok else ""

    ok, output = _run_git(project.path, ["branch", "-a", "--format=%(refname:short)"])
    branches = []
    if ok:
        for name in output.splitlines():
            name = name.strip()
            if not name:
                continue
            branches.append({
                "name": name,
                "current": name == current_branch,
                "is_remote": name.startswith("origin/"),
            })

    return {"is_git": True, "branches": branches, "current": current_branch}
