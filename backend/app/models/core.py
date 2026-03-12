from typing import Optional, List
from datetime import datetime, timezone
from sqlmodel import SQLModel, Field, Relationship
from sqlalchemy import UniqueConstraint

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
    default_member_id: Optional[int] = Field(default=None, foreign_key="member.id")  # 專案預設成員
    is_active: bool = Field(default=True) # 用於完全隱藏
    is_system: bool = Field(default=False) # 系統專案（AEGIS），前端禁止刪除/改名
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    lists: List["StageList"] = Relationship(back_populates="project")

class StageList(SQLModel, table=True):
    """卡片列表 (如 Backlog, Planning, Developing)"""
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id")
    name: str
    position: int = Field(default=0) # 用於排序
    member_id: Optional[int] = Field(default=None, foreign_key="member.id")  # 指派成員（覆寫預設路由）

    # 階段行為配置（通用化工作流）
    stage_type: str = Field(default="auto_process")  # manual, auto_process, auto_review, terminal
    system_instruction: Optional[str] = Field(default=None)  # 階段專屬系統指令
    prompt_template: Optional[str] = Field(default=None)  # 階段專屬 prompt 模板
    is_ai_stage: bool = Field(default=True)  # 是否為 AI 處理階段
    is_member_bound: bool = Field(default=False)  # True = member_id 鎖定不可變更

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
    is_archived: bool = Field(default=False)  # 封存後在看板隱藏
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

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
    is_archived: bool = Field(default=False, index=True)  # 封存後在看板隱藏
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    content_hash: str = ""
    file_mtime: float = Field(default=0.0)
    member_id: Optional[int] = Field(default=None, index=True)  # 執行中的成員 ID


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

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class CronLog(SQLModel, table=True):
    """排程執行記錄（每次 CronJob 觸發產生一筆）"""
    id: Optional[int] = Field(default=None, primary_key=True)
    cron_job_id: int = Field(index=True)        # 來自哪個排程
    cron_job_name: str = ""                      # 排程名稱（快照）
    card_id: int = Field(default=0)              # 當時的卡片 ID（已刪除但留記錄）
    card_title: str = ""
    project_id: int = Field(default=0, index=True)
    project_name: str = ""
    provider: str = ""                           # claude / gemini
    model: str = ""
    member_id: Optional[int] = Field(default=None)
    status: str = ""                             # success / error / timeout
    output: str = Field(default="")              # AI 完整輸出
    error_message: str = Field(default="")       # 錯誤訊息
    prompt_snapshot: str = Field(default="")     # 當次實際送出的 prompt（快照）
    duration_ms: int = Field(default=0)
    input_tokens: int = Field(default=0)
    output_tokens: int = Field(default=0)
    cache_read_tokens: int = Field(default=0)
    cache_creation_tokens: int = Field(default=0)
    cost_usd: float = Field(default=0.0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SystemSetting(SQLModel, table=True):
    """系統設定 key-value store"""
    key: str = Field(primary_key=True)
    value: str = Field(default="")


# ==========================================
# 多帳號管理 (Multi-Account)
# ==========================================
class Account(SQLModel, table=True):
    """AI 帳號（支援 API Key 或 CLI Token 兩種認證方式）"""
    id: Optional[int] = Field(default=None, primary_key=True)
    provider: str  # "claude" | "gemini" | "openai"
    name: str  # 顯示名稱，如 "Max 小良"
    auth_type: str = "cli"  # "api_key" | "cli"
    # API Key 認證
    api_key: str = ""  # sk-ant-api... 或 AIza... 或 sk-proj-...
    # CLI 認證（OAuth Token）
    oauth_token: str = ""  # sk-ant-oat01-... 或空
    oauth_token_set_at: int = Field(default=0)  # 時間戳（毫秒）
    # 舊欄位（向後相容）
    credential_file: str = ""  # profile 檔名（舊方式）
    subscription: str = ""  # "max" / "pro" / "ai-pro"
    email: str = ""
    is_healthy: bool = Field(default=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


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
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


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
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class MemberDialogue(SQLModel, table=True):
    """成員對話記錄（AVG 風格）"""
    id: Optional[int] = Field(default=None, primary_key=True)
    member_id: int = Field(index=True)
    card_id: Optional[int] = Field(default=None)
    card_title: str = ""
    project_name: str = ""
    dialogue_type: str = ""  # task_complete | task_failed | task_started
    text: str = ""
    status: str = ""  # success | error
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class MemberAccount(SQLModel, table=True):
    """成員-帳號綁定（含優先順序與模型設定）"""
    id: Optional[int] = Field(default=None, primary_key=True)
    member_id: int = Field(foreign_key="member.id")
    account_id: int = Field(foreign_key="account.id")
    priority: int = Field(default=0)  # 0=主要, 1=備用1, 2=備用2...
    model: str = ""  # "opus" / "sonnet" / "gemini-2.5-flash" 等


class ChannelBinding(SQLModel, table=True):
    """頻道綁定 — 用戶/專案與通訊頻道的對應"""
    id: Optional[int] = Field(default=None, primary_key=True)
    platform: str = Field(index=True)  # telegram, line, discord, slack, wecom, feishu
    user_id: str = Field(index=True)   # 平台用戶 ID
    chat_id: str                        # 發送訊息的目標 chat ID
    user_name: Optional[str] = None     # 顯示名稱（方便識別）

    # 綁定對象
    entity_type: str = Field(default="global")  # global, project, member
    entity_id: Optional[int] = None             # project_id 或 member_id

    # 通知設定
    notify_on_complete: bool = Field(default=True)   # 任務完成時通知
    notify_on_fail: bool = Field(default=True)       # 任務失敗時通知
    notify_on_start: bool = Field(default=False)     # 任務開始時通知

    # P2: 關聯到 BotUser（可選，向後相容）
    bot_user_id: Optional[int] = Field(default=None, foreign_key="botuser.id")

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ==========================================
# P2: Bot 用戶與權限系統
# ==========================================
class BotUser(SQLModel, table=True):
    """Bot 用戶（真人）"""
    __table_args__ = (
        UniqueConstraint("platform", "platform_user_id", name="uq_botuser_platform_user"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)

    # 平台身份
    platform: str = Field(index=True)       # telegram, line, discord...
    platform_user_id: str = Field(index=True)
    username: Optional[str] = None          # 顯示名稱

    # 權限
    level: int = Field(default=0)           # 0=未驗證, 1=訪客, 2=成員, 3=管理員
    is_active: bool = Field(default=True)

    # 綁定（預設 Member，用於對話）
    default_member_id: Optional[int] = Field(default=None, foreign_key="member.id")

    # 時間
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_active_at: Optional[datetime] = None

    # 安全性
    failed_verify_count: int = Field(default=0)      # 驗證失敗次數
    last_failed_at: Optional[datetime] = None        # 最後失敗時間
    locked_until: Optional[datetime] = None          # 鎖定到期時間


class BotUserPermission(SQLModel, table=True):
    """細粒度權限控制（舊版，保留向後相容）"""
    id: Optional[int] = Field(default=None, primary_key=True)
    bot_user_id: int = Field(foreign_key="botuser.id", index=True)

    # 權限類型
    permission: str         # "view", "execute", "create", "admin"

    # 資源範圍（可選）
    resource_type: Optional[str] = None   # "project", "member"
    resource_id: Optional[int] = None     # 具體 ID，null = 全部


class BotUserProject(SQLModel, table=True):
    """用戶與專案的多對多關聯（權限控制）"""
    __tablename__ = "bot_user_project"
    __table_args__ = (
        UniqueConstraint("bot_user_id", "project_id", name="uq_botuserproject"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    bot_user_id: int = Field(foreign_key="botuser.id", index=True)
    project_id: int = Field(foreign_key="project.id", index=True)

    # === 身份描述（給 AI 讀的自然語言） ===
    display_name: str = Field(default="")         # "王小華"
    description: str = Field(default="")          # "案場業主，可查看發電資料，不可修改設定"

    # === 硬性權限（程式碼強制檢查，防止 AI 誤判） ===
    can_view: bool = Field(default=True)          # 可查看卡片
    can_create_card: bool = Field(default=False)  # 可建立卡片
    can_run_task: bool = Field(default=False)     # 可執行任務
    can_comment: bool = Field(default=True)       # 可留言
    can_access_sensitive: bool = Field(default=False)  # 可存取敏感資料

    # 預設專案（建卡時優先使用）
    is_default: bool = Field(default=False)

    # 元資料
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: Optional[int] = Field(default=None)  # 誰授權的（BotUser ID）


class BotUserMember(SQLModel, table=True):
    """用戶與 Member 的多對多關聯"""
    __table_args__ = (
        UniqueConstraint("bot_user_id", "member_id", name="uq_botusermember"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    bot_user_id: int = Field(foreign_key="botuser.id", index=True)
    member_id: int = Field(foreign_key="member.id", index=True)

    # 關聯屬性
    is_default: bool = Field(default=False)     # 是否為預設 Member
    can_switch: bool = Field(default=True)      # 是否可切換到此 Member
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class InviteCode(SQLModel, table=True):
    """邀請碼"""
    id: Optional[int] = Field(default=None, primary_key=True)
    code: str = Field(index=True, unique=True)  # "CUSTA2024"

    # 配置
    target_level: int = Field(default=1)        # 驗證後的權限等級
    target_member_id: Optional[int] = Field(default=None, foreign_key="member.id")
    allowed_projects: Optional[str] = None      # JSON: [1, 2, 3]

    # 用戶身份描述（驗證時自動填入 BotUserProject）
    user_display_name: str = Field(default="")  # "王小華"
    user_description: str = Field(default="")   # "案場業主，可查看發電資料..."

    # 預設權限（驗證時自動填入 BotUserProject）
    default_can_view: bool = Field(default=True)
    default_can_create_card: bool = Field(default=False)
    default_can_run_task: bool = Field(default=False)
    default_can_access_sensitive: bool = Field(default=False)

    # 使用限制
    max_uses: int = Field(default=1)
    used_count: int = Field(default=0)
    expires_at: Optional[datetime] = None

    # 元資料
    created_by: Optional[int] = Field(default=None, foreign_key="botuser.id")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    note: str = ""          # "給客戶A用"


class ChatSession(SQLModel, table=True):
    """對話 Session（User × Member × Channel）"""
    __table_args__ = (
        UniqueConstraint("bot_user_id", "member_id", "chat_id", name="uq_chatsession"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    bot_user_id: int = Field(foreign_key="botuser.id", index=True)
    member_id: int = Field(foreign_key="member.id", index=True)
    chat_id: str = Field(index=True)        # 對話頻道 ID

    # Token 統計（用於限流）
    total_input_tokens: int = Field(default=0)
    total_output_tokens: int = Field(default=0)
    message_count: int = Field(default=0)

    # 時間
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_message_at: Optional[datetime] = None


class ChatMessage(SQLModel, table=True):
    """對話訊息（獨立儲存，支援高效查詢）"""
    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: int = Field(foreign_key="chatsession.id", index=True)

    role: str               # "user" | "assistant"
    content: str            # 訊息內容
    input_tokens: int = Field(default=0)
    output_tokens: int = Field(default=0)

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ==========================================
# Email 頻道
# ==========================================
class EmailMessage(SQLModel, table=True):
    """收到的 Email 紀錄（含 AI 分類結果）"""
    id: Optional[int] = Field(default=None, primary_key=True)

    # IMAP 信封
    uid: str = Field(index=True, unique=True)     # IMAP UID — 去重 key
    message_id: str = Field(default="")            # RFC Message-ID header
    in_reply_to: str = Field(default="")           # 串連用
    from_address: str = Field(default="")
    from_name: str = Field(default="")
    to_address: str = Field(default="")
    subject: str = Field(default="")
    date: Optional[datetime] = None
    body_text: str = Field(default="")             # 純文字（截斷）
    attachment_names: str = Field(default="[]")    # JSON array

    # AI 分類
    category: str = Field(default="unclassified")  # actionable / informational / spam / newsletter
    urgency: str = Field(default="unknown")        # high / medium / low
    summary: str = Field(default="")               # AI 摘要 1-3 句
    suggested_action: str = Field(default="")      # AI 建議動作
    project_id: Optional[int] = Field(default=None)

    # 處理狀態
    is_processed: bool = Field(default=False)
    is_synced_to_onestack: bool = Field(default=False)
    card_id: Optional[int] = Field(default=None)

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
