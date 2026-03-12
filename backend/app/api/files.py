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

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session

from app.database import get_session
from app.models.core import Project

router = APIRouter(tags=["files"])

# 排除的目錄/檔案
EXCLUDED_NAMES = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    "dist", ".next", ".nuxt", ".cache", ".DS_Store",
    "Thumbs.db", ".env", ".env.local",
}

MAX_FILE_SIZE = 1 * 1024 * 1024  # 1MB


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


@router.get("/projects/{project_id}/files")
def list_files(
    project_id: int,
    path: str = Query("", description="相對路徑，空字串表示根目錄"),
    session: Session = Depends(get_session),
):
    """列出目錄內容（單層，lazy load）"""
    project = _get_project(project_id, session)
    target = _resolve_safe_path(project.path, path)

    if not target.exists():
        raise HTTPException(status_code=404, detail="Directory not found")
    if not target.is_dir():
        raise HTTPException(status_code=400, detail="Not a directory")

    base = Path(project.path).resolve()
    entries: list[dict] = []

    try:
        for item in sorted(target.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            if item.name in EXCLUDED_NAMES:
                continue
            if item.name.startswith(".") and item.name not in (".gitignore", ".env.example", ".aegis"):
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
):
    """讀取檔案內容"""
    project = _get_project(project_id, session)
    target = _resolve_safe_path(project.path, path)

    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")
    if not target.is_file():
        raise HTTPException(status_code=400, detail="Not a file")

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
