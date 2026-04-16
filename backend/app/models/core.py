from typing import Optional, List
from datetime import datetime, timezone
from pydantic import field_validator
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
    allow_anonymous: bool = Field(default=False)  # 允許未登入瀏覽
    room_id: Optional[int] = Field(default=None, foreign_key="room.id")  # 所屬空間
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    lists: List["StageList"] = Relationship(back_populates="project")

class StageList(SQLModel, table=True):
    """卡片列表 (如 Backlog, Planning, Developing)"""
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    name: str
    description: Optional[str] = Field(default=None)  # 階段說明（如「審查階段」）
    position: int = Field(default=0) # 用於排序
    member_id: Optional[int] = Field(default=None, foreign_key="member.id")  # 指派成員（覆寫預設路由）

    # 階段行為配置
    stage_type: str = Field(default="auto_process")  # deprecated, 保留欄位避免 DB 錯誤
    system_instruction: Optional[str] = Field(default=None)  # 階段專屬系統指令
    prompt_template: Optional[str] = Field(default=None)  # 階段專屬 prompt 模板
    is_ai_stage: bool = Field(default=True)  # 是否為 AI 處理階段
    is_member_bound: bool = Field(default=False)  # True = member_id 鎖定不可變更

    # 完成/失敗後動作: none | move_to:<list_id> | archive | delete
    on_success_action: str = Field(default="none")
    on_fail_action: str = Field(default="none")
    auto_commit: bool = Field(default=False)  # 成功自動 git commit，失敗自動 shelve 到分支
    gate_enabled: bool = Field(default=False)  # 啟用 build gate 閘門檢查（語法驗證）

    project: Optional[Project] = Relationship(back_populates="lists")
    cards: List["Card"] = Relationship(back_populates="stage_list")

class Tag(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True) # 如 AI-Gemini, P0
    color: Optional[str] = Field(default="gray")

    cards: List["Card"] = Relationship(back_populates="tags", link_model=CardTagLink)

class Card(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    list_id: int = Field(foreign_key="stagelist.id", index=True)
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
    model: Optional[str] = Field(default=None)  # 卡片級模型指定（如 haiku / sonnet / opus）
    parent_id: Optional[int] = Field(default=None, index=True)  # 父卡片 ID（Leader-Worker）
    max_rounds: int = Field(default=1)  # Ralph Loop 最大迭代輪數
    acceptance_criteria: Optional[str] = Field(default=None)  # 完成條件（Sprint Contract）
    is_archived: bool = Field(default=False, index=True)  # 封存後在看板隱藏
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    content_hash: str = ""
    file_mtime: float = Field(default=0.0)
    member_id: Optional[int] = Field(default=None, index=True)  # 執行中的成員 ID
    cron_job_id: Optional[int] = Field(default=None, index=True)  # 由哪個排程建立
    total_input_tokens: int = Field(default=0)  # 累計輸入 token 數
    total_output_tokens: int = Field(default=0)  # 累計輸出 token 數
    estimated_cost_usd: float = Field(default=0.0)  # 預估費用（USD）


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
    target_list_id: Optional[int] = Field(default=None, foreign_key="stagelist.id")  # 目標列表，None=Scheduled
    api_url: Optional[str] = Field(default=None)  # 有值 → 時間到直接 POST（會議等）；None → 建卡片
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
    stage_action: str = Field(default="", sa_column_kwargs={"server_default": ""})
    # 排程完成後的流轉動作，如 move_to:42、delete、archive、none
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SystemSetting(SQLModel, table=True):
    """系統設定 key-value store"""
    key: str = Field(primary_key=True)
    value: str = Field(default="")


# ==========================================
# 同步規則 (Sync Matrix)
# ==========================================
class SyncRule(SQLModel, table=True):
    """欄位級同步規則 — 控制每個實體欄位的寫入權限與衝突策略"""
    __table_args__ = (UniqueConstraint("entity_type", "field_name"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    entity_type: str = Field(index=True)  # "card" | "stagelist" | "member" | "project"
    field_name: str  # "title" | "description" | "status" 等
    writable_by: str = Field(default="both")  # "ai" | "human" | "both"
    conflict_strategy: str = Field(default="last_write_wins")  # "last_write_wins" | "human_wins" | "ai_wins"
    is_enabled: bool = Field(default=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


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
    sprite_sheet: str = ""  # sprite sheet 路徑（如 /uploads/sprites/1/sheet_20260323.png）
    sprite_scale: float = Field(default=1.0)  # sprite 縮放比例（前端用）
    hook_profile: str = Field(default="standard")  # "minimal" | "standard" | "strict" — hook 嚴格度設定
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
    output: str = Field(default="")  # AI 完整輸出
    duration_ms: int = Field(default=0)
    input_tokens: int = Field(default=0)
    output_tokens: int = Field(default=0)
    cache_read_tokens: int = Field(default=0)
    cache_creation_tokens: int = Field(default=0)
    cost_usd: float = Field(default=0.0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class BroadcastLog(SQLModel, table=True):
    """任務廣播記錄（臨時，24 小時自動清理）"""
    id: Optional[int] = Field(default=None, primary_key=True)
    card_id: int = Field(index=True)
    line: str = ""
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


class MemberMessage(SQLModel, table=True):
    """成員間訊息記錄（AI 成員透明通訊）"""
    id: Optional[int] = Field(default=None, primary_key=True)
    from_member_id: int = Field(index=True)
    to_member_id: Optional[int] = Field(default=None, index=True)
    card_id: Optional[int] = Field(default=None, index=True)
    message_type: str = Field(default="info")  # delegate / report / question / info
    content: str = Field(default="")
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
# P2: 用戶身份與權限系統
# ==========================================
class Person(SQLModel, table=True):
    """真人身份（跨平台共用）— 一個人可有多個 BotUser（不同平台的登入帳號）"""
    id: Optional[int] = Field(default=None, primary_key=True)

    # 身份資訊
    display_name: str = Field(default="")       # 顯示名稱（如「王蕙宇」）
    description: str = Field(default="")        # 身份描述（如「財務人員，可查看報表」）

    # 權限（Person 層級）
    level: int = Field(default=0)               # 0=未驗證, 1=訪客, 2=成員, 3=管理員
    default_member_id: Optional[int] = Field(default=None, foreign_key="member.id")
    access_expires_at: Optional[datetime] = None

    # 額外資料（JSON，如 AD 帳密、自訂欄位）— 跨平台共用
    extra_json: str = Field(default="{}")

    # 時間
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class BotUser(SQLModel, table=True):
    """Bot 用戶（平台登入帳號，指向 Person）"""
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

    # 存取期限
    access_expires_at: Optional[datetime] = None     # 存取過期時間（None = 永不過期）

    # 額外資料（JSON，供 MCP/Skill 讀取，如 AD 帳密、自訂欄位等）
    extra_json: str = Field(default="{}")

    # 跨平台身份分組（同一個人的不同平台帳號共享相同的 person_id）
    person_id: int = Field(default=0, index=True)    # 0=未分組，遷移時 = self.id

    # 網頁登入（platform="web" 時使用）
    password_hash: Optional[str] = None              # scrypt 雜湊密碼

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


class PersonProject(SQLModel, table=True):
    """Person 與專案的多對多關聯（權限控制，取代 BotUserProject）"""
    __tablename__ = "person_project"
    __table_args__ = (
        UniqueConstraint("person_id", "project_id", name="uq_personproject"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    person_id: int = Field(foreign_key="person.id", index=True)
    project_id: int = Field(foreign_key="project.id", index=True)

    # 身份描述（給 AI 讀的）
    display_name: str = Field(default="")
    description: str = Field(default="")

    # 硬性權限
    can_view: bool = Field(default=True)
    can_create_card: bool = Field(default=False)
    can_run_task: bool = Field(default=False)
    can_comment: bool = Field(default=True)
    can_access_sensitive: bool = Field(default=False)

    is_default: bool = Field(default=False)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: Optional[int] = Field(default=None)


class PersonMember(SQLModel, table=True):
    """Person 與 Member 的多對多關聯（取代 BotUserMember）"""
    __tablename__ = "person_member"
    __table_args__ = (
        UniqueConstraint("person_id", "member_id", name="uq_personmember"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    person_id: int = Field(foreign_key="person.id", index=True)
    member_id: int = Field(foreign_key="member.id", index=True)

    is_default: bool = Field(default=False)
    can_switch: bool = Field(default=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class InviteCode(SQLModel, table=True):
    """邀請碼"""
    id: Optional[int] = Field(default=None, primary_key=True)
    code: str = Field(index=True, unique=True)  # "CUSTA2024"

    # 配置
    target_level: int = Field(default=1)        # 驗證後的權限等級
    target_member_id: Optional[int] = Field(default=None, foreign_key="member.id")
    allowed_projects: Optional[str] = None      # JSON: [1, 2, 3]

    # 用戶身份描述（驗證時自動填入 PersonProject）
    user_display_name: str = Field(default="")  # "王小華"
    user_description: str = Field(default="")   # "案場業主，可查看發電資料..."

    # 預設權限（驗證時自動填入 PersonProject）
    default_can_view: bool = Field(default=True)
    default_can_create_card: bool = Field(default=False)
    default_can_run_task: bool = Field(default=False)
    default_can_access_sensitive: bool = Field(default=False)

    # 使用限制
    max_uses: int = Field(default=1)
    used_count: int = Field(default=0)
    expires_at: Optional[datetime] = None

    # 存取期限（驗證後的有效天數）
    access_valid_days: Optional[int] = Field(default=None)  # None = 永久

    # 跨平台綁定（第一個使用此邀請碼的人的 person_id）
    owner_person_id: Optional[int] = None  # 後續使用者自動綁定到同一 person

    # 元資料
    created_by: Optional[int] = Field(default=None, foreign_key="botuser.id")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    note: str = ""          # "給客戶A用"


# ==========================================
# Embedding 向量儲存
# ==========================================
class EmbeddingRecord(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    entity_type: str = Field(index=True)          # "memory" | "card" | "document"
    entity_key: str = Field(index=True)            # 檔案路徑或唯一識別碼
    member_slug: Optional[str] = Field(default=None, index=True)
    content_hash: str = ""                         # SHA256 of content
    vector_json: str = ""                          # JSON array of floats
    model_name: str = "text-embedding-3-small"
    dimension: int = 1536
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


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
class ProjectEnvVar(SQLModel, table=True):
    """專案環境變數（注入到 AI 任務的 subprocess 環境）"""
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    key: str          # 變數名稱，如 SUPABASE_URL
    value: str        # 變數值
    is_secret: bool = Field(default=True)  # True = 前端只顯示 ****
    description: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


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


# ==========================================
# 原始訊息收集（Passive 模式）
# ==========================================
class RawMessage(SQLModel, table=True):
    """原始訊息存檔（passive 模式，只收不回）"""
    id: Optional[int] = Field(default=None, primary_key=True)

    # 來源識別
    platform: str = Field(index=True)             # "line"
    source_type: str = Field(default="user")      # "user" | "group" | "room"
    source_id: str = Field(index=True)             # group_id / room_id / user_id
    user_id: str = Field(default="")               # 發話者（群組中可能為空）

    # 事件
    event_type: str = Field(default="message")     # message / follow / join / leave / postback
    content_type: str = Field(default="text")      # text / image / video / audio / sticker / file
    content: str = Field(default="")               # 文字內容（非文字則為空）
    payload: str = Field(default="{}")             # 完整原始 event JSON

    # 處理狀態
    is_processed: bool = Field(default=False, index=True)
    processed_at: Optional[datetime] = None

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RawMessageUser(SQLModel, table=True):
    """外部平台用戶快取（LINE profile 等）"""
    __table_args__ = (
        UniqueConstraint("platform", "user_id", name="uq_rawmsguser"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    platform: str = Field(index=True)
    user_id: str = Field(index=True)
    display_name: str = Field(default="")
    picture_url: str = Field(default="")
    status_message: str = Field(default="")

    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RawMessageGroup(SQLModel, table=True):
    """外部平台群組快取（LINE group summary 等）"""
    __table_args__ = (
        UniqueConstraint("platform", "group_id", name="uq_rawmsggroup"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    platform: str = Field(index=True)
    group_id: str = Field(index=True)
    group_name: str = Field(default="")
    picture_url: str = Field(default="")
    member_count: int = Field(default=0)
    project_id: Optional[int] = Field(default=None, foreign_key="project.id", index=True)

    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ==========================================
# 房間 & 網域（多空間 + 網域綁定）
# ==========================================
class Room(SQLModel, table=True):
    """虛擬辦公室房間 — 每個房間有自己的佈局和成員"""
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str                                    # "研發部", "維運中心"
    description: str = Field(default="")
    layout_json: str = Field(default="{}")       # Phaser 辦公室佈局
    layout_type: str = Field(default="tiled")
    position: int = Field(default=0)             # 顯示順序

    @field_validator("layout_type")
    @classmethod
    def _validate_layout_type(cls, v: str) -> str:
        if v not in ("classic", "tiled"):
            raise ValueError(f"layout_type must be 'classic' or 'tiled', got '{v}'")
        return v

    is_active: bool = Field(default=True)
    allow_anonymous: bool = Field(default=False)  # 允許未登入瀏覽
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RoomProject(SQLModel, table=True):
    """[deprecated] 房間可見專案 — 已改用 Project.room_id 直接關聯"""
    __table_args__ = (
        UniqueConstraint("room_id", "project_id", name="uq_roomproject"),
    )
    id: Optional[int] = Field(default=None, primary_key=True)
    room_id: int = Field(foreign_key="room.id", index=True)
    project_id: int = Field(foreign_key="project.id", index=True)


class RoomMember(SQLModel, table=True):
    """房間成員（多對多）"""
    __table_args__ = (
        UniqueConstraint("room_id", "member_id", name="uq_roommember"),
    )
    id: Optional[int] = Field(default=None, primary_key=True)
    room_id: int = Field(foreign_key="room.id", index=True)
    member_id: int = Field(foreign_key="member.id", index=True)
    desk_index: int = Field(default=0)           # 房間內的座位位置


class WebhookConfig(SQLModel, table=True):
    """用戶自定義 Webhook 配置（每個專案可建立多個命名 webhook）"""
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_webhookconfig_project_name"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    name: str = Field(index=True)                    # 顯示名稱，專案內唯一
    url: str                                          # 目標 URL
    active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ==========================================
# Prompt Queue（任務提示佇列化）
# ==========================================
class PromptQueueEntry(SQLModel, table=True):
    """Prompt 佇列項目 — 任務提示佇列化，支援優先級出隊"""
    id: Optional[int] = Field(default=None, primary_key=True)
    queue_id: str = Field(index=True, unique=True)       # UUID，外部追蹤用
    session_id: str = Field(index=True)                   # chat_key，如 "telegram:123:xiao-yin"
    prompt_text: str                                       # 實際要送出的提示文字
    priority: int = Field(default=1)                      # 數值越大優先級越高
    status: str = Field(default="pending", index=True)    # pending | processing | processed | failed
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class NamedSession(SQLModel, table=True):
    """命名工作區 Session — 跨卡片的持久工作區，AI 成員可在多張卡片間共用"""
    __table_args__ = (
        UniqueConstraint("member_id", "name", name="uq_namedsession_member_name"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    member_id: int = Field(foreign_key="member.id", index=True)
    name: str = Field(index=True)          # session 名稱，如 "refactor-auth"
    project_id: Optional[int] = Field(default=None, foreign_key="project.id")
    description: str = Field(default="")   # 用途描述
    workspace_path: str = Field(default="")  # 實際工作區絕對路徑

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Domain(SQLModel, table=True):
    """網域綁定 — 控制該網域的登入和引導頁設定"""
    id: Optional[int] = Field(default=None, primary_key=True)
    hostname: str = Field(index=True, unique=True)  # "aegis.greenshepherd.com.tw"
    name: str = Field(default="")                    # 顯示名稱
    room_ids_json: str = Field(default="[]")         # [deprecated] 舊版房間綁定，新版不使用
    is_default: bool = Field(default=False)          # 未匹配時的 fallback
    is_active: bool = Field(default=True)
    require_login: bool = Field(default=False)       # 此網域是否強制登入
    show_onboarding: bool = Field(default=True)      # 此網域是否顯示引導頁
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
