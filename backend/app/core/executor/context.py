"""
MemberContext — 統一成員解析（Worker / Runner 共用）

合併原本分散在 worker.py 和 chat_handler.py 中的成員/帳號查詢邏輯。
"""
import logging
from dataclasses import dataclass, field
from typing import Optional, List

logger = logging.getLogger(__name__)


@dataclass
class AccountInfo:
    """單一帳號的認證資訊"""
    provider: str
    model: str
    auth_info: dict  # {auth_type, oauth_token, api_key}
    name: str


@dataclass
class MemberContext:
    """成員完整上下文 — 一次查詢，到處使用"""
    member_id: Optional[int] = None
    member_slug: Optional[str] = None
    member_name: Optional[str] = None
    accounts: List[AccountInfo] = field(default_factory=list)
    soul: str = ""
    mcp_config_path: Optional[str] = None

    @property
    def primary_account(self) -> Optional[AccountInfo]:
        return self.accounts[0] if self.accounts else None

    @property
    def primary_provider(self) -> str:
        return self.primary_account.provider if self.primary_account else "claude"

    @property
    def primary_model(self) -> str:
        """成員帳號設定的 model（可能為空）"""
        return self.primary_account.model if self.primary_account else ""

    def effective_model(self, mode: str = "task") -> str:
        """帶 fallback 的 model — 成員有設定就用，沒有則按 provider + mode 給預設。"""
        if self.primary_model:
            return self.primary_model
        from app.core.model_registry import get_provider_default
        return get_provider_default(self.primary_provider, mode)

    @property
    def primary_auth(self) -> dict:
        return self.primary_account.auth_info if self.primary_account else {}

    @property
    def has_member(self) -> bool:
        return self.member_id is not None

    def accounts_as_tuples(self) -> list:
        """向後相容：回傳 [(provider, model, auth_info, name), ...]"""
        return [(a.provider, a.model, a.auth_info, a.name) for a in self.accounts]


def _fetch_accounts(member_id: int) -> List[AccountInfo]:
    """查詢成員所有健康帳號（按 priority 排序）"""
    from sqlmodel import Session, select
    from app.database import engine
    from app.models.core import MemberAccount, Account

    with Session(engine) as session:
        stmt = select(MemberAccount).where(
            MemberAccount.member_id == member_id
        ).order_by(MemberAccount.priority)
        bindings = session.exec(stmt).all()

        results = []
        for binding in bindings:
            account = session.get(Account, binding.account_id)
            if account and account.is_healthy:
                results.append(AccountInfo(
                    provider=account.provider,
                    model=binding.model or "",
                    auth_info={
                        "auth_type": getattr(account, "auth_type", "cli"),
                        "oauth_token": getattr(account, "oauth_token", "") or "",
                        "api_key": getattr(account, "api_key", "") or "",
                    },
                    name=account.name or f"account-{account.id}",
                ))
        return results


def _build_context(member_id: int, member_slug: str, member_name: str) -> MemberContext:
    """從已知 member 建立完整 MemberContext"""
    from app.core.member_profile import get_soul_content
    from app.core.executor.auth import get_mcp_config_path_by_slug

    accounts = _fetch_accounts(member_id)
    soul = get_soul_content(member_slug) if member_slug else ""
    mcp_path = get_mcp_config_path_by_slug(member_slug) if member_slug else None

    return MemberContext(
        member_id=member_id,
        member_slug=member_slug,
        member_name=member_name,
        accounts=accounts,
        soul=soul,
        mcp_config_path=mcp_path,
    )


def resolve_member_for_task(stage_list_id: int) -> MemberContext:
    """解析卡片任務應該由哪個成員執行（三層路由）。

    1. 列表級指派（StageList.member_id）
    2. 專案預設成員（Project.default_member_id）
    3. 無指派 → 空 MemberContext
    """
    from sqlmodel import Session
    from app.database import engine
    from app.models.core import StageList, Project, Member

    with Session(engine) as session:
        # 1. 列表級指派
        stage_list = session.get(StageList, stage_list_id)
        if stage_list and stage_list.member_id:
            member = session.get(Member, stage_list.member_id)
            if member:
                ctx = _build_context(member.id, member.slug, member.name)
                logger.info(
                    f"[Router] List '{stage_list.name}' → {member.name} ({len(ctx.accounts)} accounts)"
                )
                return ctx

        # 2. 專案預設成員
        if stage_list:
            project = session.get(Project, stage_list.project_id)
            if project and project.default_member_id:
                member = session.get(Member, project.default_member_id)
                if member:
                    ctx = _build_context(member.id, member.slug, member.name)
                    logger.info(
                        f"[Router] Project '{project.name}' default → {member.name} ({len(ctx.accounts)} accounts)"
                    )
                    return ctx

    # 3. 無指派
    return MemberContext()


def resolve_member_for_chat(member_id: int) -> MemberContext:
    """解析即時對話的成員上下文。

    從指定 member_id 建立完整 MemberContext（含帳號、soul、MCP）。
    """
    from sqlmodel import Session
    from app.database import engine
    from app.models.core import Member

    if not member_id:
        return MemberContext()

    with Session(engine) as session:
        member = session.get(Member, member_id)
        if not member:
            return MemberContext()

        return _build_context(member.id, member.slug, member.name)
