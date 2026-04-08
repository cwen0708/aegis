"""Named Workspace — 跨卡片的持久命名工作區。

與 task_workspace（一次性）不同，named workspace 不會自動清理，
讓 AI 成員能在多張卡片間共用同一個工作區。

工作區目錄：.aegis/workspaces/session-{name}/
"""
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.core.paths import WORKSPACES_ROOT
from app.models.core import NamedSession

logger = logging.getLogger(__name__)

_SAFE_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_\-]{0,62}$")


def _validate_name(name: str) -> str:
    """驗證 session 名稱：英數開頭、可含 - _、1-63 字元。"""
    if not _SAFE_NAME_RE.match(name):
        raise ValueError(
            f"Invalid session name '{name}': "
            "must start with alphanumeric, contain only [a-zA-Z0-9_-], max 63 chars"
        )
    return name


def create_named_workspace(
    db: Session,
    member_id: int,
    name: str,
    project_id: Optional[int] = None,
    description: str = "",
) -> NamedSession:
    """建立命名工作區：寫入 DB 記錄並建立目錄。

    Raises:
        ValueError: name 格式不合法
        IntegrityError: 同 member 已有同名 session
    """
    _validate_name(name)

    ws_dir = WORKSPACES_ROOT / f"session-{name}"
    ws_dir.mkdir(parents=True, exist_ok=True)

    session = NamedSession(
        member_id=member_id,
        name=name,
        project_id=project_id,
        description=description,
        workspace_path=str(ws_dir),
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    logger.info(f"[NamedWorkspace] Created session '{name}' for member {member_id} at {ws_dir}")
    return session


def get_named_workspace(
    db: Session,
    member_id: int,
    name: str,
) -> Optional[NamedSession]:
    """查詢指定成員的命名工作區（by name）。"""
    stmt = select(NamedSession).where(
        NamedSession.member_id == member_id,
        NamedSession.name == name,
    )
    return db.exec(stmt).first()


def list_named_workspaces(
    db: Session,
    member_id: int,
) -> List[NamedSession]:
    """列出指定成員的所有命名工作區。"""
    stmt = (
        select(NamedSession)
        .where(NamedSession.member_id == member_id)
        .order_by(NamedSession.created_at.desc())
    )
    return list(db.exec(stmt).all())
