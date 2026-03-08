from typing import Optional, List
from datetime import datetime
from sqlmodel import SQLModel, Field, Relationship

# ==========================================
# 關聯表 (Link Tables)
# ==========================================
class CardTagLink(SQLModel, table=True):
    card_id: Optional[int] = Field(default=None, foreign_key="card.id", primary_key=True)
    tag_id: Optional[int] = Field(default=None, foreign_key="tag.id", primary_key=True)

# ==========================================
# 實體表 (Entities)
# ==========================================
class Project(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    path: str # 本地實體路徑，如 G:\cwen0708\infinite-novel
    deploy_type: Optional[str] = Field(default="none")
    default_provider: Optional[str] = Field(default="auto") # auto, gemini, claude
    is_active: bool = Field(default=True) # 用於完全隱藏
    is_system: bool = Field(default=False) # 系統專案（AEGIS），前端禁止刪除/改名
    created_at: datetime = Field(default_factory=datetime.utcnow)

    lists: List["StageList"] = Relationship(back_populates="project")

class StageList(SQLModel, table=True):
    """卡片列表 (如 Backlog, Planning, Developing)"""
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id")
    name: str
    position: int = Field(default=0) # 用於排序
    member_id: Optional[int] = Field(default=None, foreign_key="member.id")  # 指派成員（覆寫預設路由）

    project: Optional[Project] = Relationship(back_populates="lists")
    cards: List["Card"] = Relationship(back_populates="stage_list")

class Tag(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True) # 如 AI-Gemini, P0
    color: Optional[str] = Field(default="gray")

    cards: List["Card"] = Relationship(back_populates="tags", link_model=CardTagLink)

class Card(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    list_id: int = Field(foreign_key="stagelist.id")
    title: str
    description: Optional[str] = None
    content: str = Field(default="") # 詳細的 Markdown 內容，傳給 AI 的 prompt
    status: str = Field(default="idle") # idle, running, failed, completed
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    stage_list: Optional[StageList] = Relationship(back_populates="cards")
    tags: List[Tag] = Relationship(back_populates="cards", link_model=CardTagLink)

class CardIndex(SQLModel, table=True):
    """SQLite cache index for MD card files — NOT source of truth."""
    card_id: int = Field(primary_key=True)
    project_id: int = Field(default=0, index=True)
    file_path: str = ""
    list_id: int = Field(default=0, index=True)
    status: str = Field(default="idle", index=True)
    title: str = ""
    description: Optional[str] = None
    tags_json: str = Field(default="[]")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    content_hash: str = ""
    file_mtime: float = Field(default=0.0)


class CronJob(SQLModel, table=True):
    """本地化的定時排程任務模板 (取代 Supabase 的 ai_prompts)"""
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id")
    name: str
    description: Optional[str] = None
    system_instruction: Optional[str] = None
    prompt_template: str = Field(default="")
    cron_expression: str
    is_enabled: bool = Field(default=True)
    is_system: bool = Field(default=False)  # 系統排程，前端禁止刪除
    next_scheduled_at: Optional[datetime] = None
    
    # 存放原本 Supabase 裡的 metadata (field_id, event_type 等)，用 JSON 字串存
    metadata_json: str = Field(default="{}")

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class SystemSetting(SQLModel, table=True):
    """系統設定 key-value store"""
    key: str = Field(primary_key=True)
    value: str = Field(default="")


# ==========================================
# 多帳號管理 (Multi-Account)
# ==========================================
class Account(SQLModel, table=True):
    """AI 帳號（實體的 CLI 登入憑證）"""
    id: Optional[int] = Field(default=None, primary_key=True)
    provider: str  # "claude" | "gemini"
    name: str  # 顯示名稱，如 "Max 小良"
    credential_file: str  # profile 檔名，如 "claude-max-a.json"
    subscription: str = ""  # "max" / "pro" / "ai-pro"
    email: str = ""
    is_healthy: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Member(SQLModel, table=True):
    """AI 團隊成員（虛擬角色）"""
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str  # "財務小陳"
    slug: str = ""  # 資料夾名稱，如 "xiao-jun"
    avatar: str = ""  # emoji
    role: str = ""  # "資深開發者"
    description: str = ""
    sprite_index: int = Field(default=0)  # 小人物圖索引 0-5
    portrait: str = ""  # 立繪圖片路徑
    created_at: datetime = Field(default_factory=datetime.utcnow)


class TaskLog(SQLModel, table=True):
    """任務執行記錄（含 token 用量）"""
    id: Optional[int] = Field(default=None, primary_key=True)
    card_id: int = Field(default=0)
    card_title: str = ""
    project_name: str = ""
    provider: str = ""  # claude / gemini
    model: str = ""  # opus, sonnet, gemini-2.5-flash...
    member_id: Optional[int] = Field(default=None)
    status: str = ""  # success / error / timeout
    duration_ms: int = Field(default=0)
    input_tokens: int = Field(default=0)
    output_tokens: int = Field(default=0)
    cache_read_tokens: int = Field(default=0)
    cache_creation_tokens: int = Field(default=0)
    cost_usd: float = Field(default=0.0)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class MemberAccount(SQLModel, table=True):
    """成員-帳號綁定（含優先順序與模型設定）"""
    id: Optional[int] = Field(default=None, primary_key=True)
    member_id: int = Field(foreign_key="member.id")
    account_id: int = Field(foreign_key="account.id")
    priority: int = Field(default=0)  # 0=主要, 1=備用1, 2=備用2...
    model: str = ""  # "opus" / "sonnet" / "gemini-2.5-flash" 等
