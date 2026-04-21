import sqlite3
import logging
from sqlmodel import SQLModel, create_engine, Session
from pathlib import Path

logger = logging.getLogger(__name__)

# 使用本地 SQLite 資料庫，實現極致可攜性
DB_FILE = Path(__file__).parent.parent / "local.db"
sqlite_url = f"sqlite:///{DB_FILE}"

# echo=True 可以在開發時看到 SQL 語法，正式環境可關閉
engine = create_engine(sqlite_url, echo=False)

def _auto_add_missing_columns():
    """自動偵測 SQLModel 定義與實際 DB schema 的差異，補上缺少的欄位。
    這讓 hot update 後新欄位自動生效，不需要手動寫 ALTER TABLE。"""
    conn = sqlite3.connect(DB_FILE)
    try:
        cur = conn.cursor()
        existing_tables = {row[0] for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}

        for table_name, table in SQLModel.metadata.tables.items():
            if table_name not in existing_tables:
                continue  # 新表由 create_all 處理
            existing_cols = {row[1] for row in cur.execute(f"PRAGMA table_info({table_name})").fetchall()}
            for col in table.columns:
                if col.name in existing_cols:
                    continue
                # 推斷 SQLite 類型
                col_type = str(col.type)
                if "INTEGER" in col_type or "BOOLEAN" in col_type:
                    sql_type = "INTEGER"
                elif "FLOAT" in col_type or "REAL" in col_type:
                    sql_type = "REAL"
                elif "DATETIME" in col_type:
                    sql_type = "DATETIME"
                else:
                    sql_type = "TEXT"
                # 推斷預設值
                default = ""
                if col.default is not None and col.default.arg is not None:
                    d = col.default.arg
                    if isinstance(d, bool):
                        default = f" DEFAULT {1 if d else 0}"
                    elif isinstance(d, (int, float)):
                        default = f" DEFAULT {d}"
                    elif isinstance(d, str):
                        default = f" DEFAULT '{d}'"
                elif col.nullable:
                    default = ""  # nullable, no default needed
                try:
                    cur.execute(f"ALTER TABLE {table_name} ADD COLUMN {col.name} {sql_type}{default}")
                    logger.info(f"[AutoMigrate] Added '{col.name}' ({sql_type}{default}) to {table_name}")
                except Exception as e:
                    logger.warning(f"[AutoMigrate] Failed to add {table_name}.{col.name}: {e}")
        conn.commit()
    except Exception as e:
        logger.warning(f"[AutoMigrate] {e}")
    finally:
        conn.close()


def _migrate_db():
    """執行必要的 schema migration（SQLite ALTER TABLE）"""
    # 先自動補缺欄位
    _auto_add_missing_columns()

    conn = sqlite3.connect(DB_FILE)
    try:
        cur = conn.cursor()
        # MemberAccount 加 model 欄位
        cols = [row[1] for row in cur.execute("PRAGMA table_info(memberaccount)").fetchall()]
        if "model" not in cols:
            cur.execute("ALTER TABLE memberaccount ADD COLUMN model TEXT DEFAULT ''")
            logger.info("[Migration] Added 'model' column to memberaccount")
            # 從 member 表遷移舊資料：把 member.model 寫到 priority=0 的 binding
            try:
                cur.execute("""
                    UPDATE memberaccount SET model = (
                        SELECT m.model FROM member m WHERE m.id = memberaccount.member_id
                    ) WHERE priority = 0 AND EXISTS (
                        SELECT 1 FROM member m WHERE m.id = memberaccount.member_id AND m.model != ''
                    )
                """)
                logger.info("[Migration] Migrated model values from member to memberaccount")
            except Exception:
                pass  # member 表可能已經沒有 model 欄位
        # StageList 加 is_member_bound 欄位
        cols = [row[1] for row in cur.execute("PRAGMA table_info(stagelist)").fetchall()]
        if "is_member_bound" not in cols:
            cur.execute("ALTER TABLE stagelist ADD COLUMN is_member_bound INTEGER DEFAULT 0")
            logger.info("[Migration] Added 'is_member_bound' to stagelist")

        # TaskLog 加 output 欄位
        cols = [row[1] for row in cur.execute("PRAGMA table_info(tasklog)").fetchall()]
        if "output" not in cols:
            cur.execute("ALTER TABLE tasklog ADD COLUMN output TEXT DEFAULT ''")
            logger.info("[Migration] Added 'output' column to tasklog")

        # CronLog 加 delivery_error 欄位（區分 agent 錯誤與投遞失敗）
        try:
            cur.execute("ALTER TABLE cronlog ADD COLUMN delivery_error TEXT DEFAULT ''")
            logger.info("[Migration] Added 'delivery_error' column to cronlog")
        except Exception:
            pass

        # CronLog.card_id 索引（加速 /cards/{id}/cost 的 actual_model 查詢）
        # ORM 層 Field(index=True) 只對新建 DB 生效；既存 DB 需手動 CREATE INDEX
        try:
            cur.execute("CREATE INDEX IF NOT EXISTS ix_cronlog_card_id ON cronlog(card_id)")
            logger.info("[Migration] Ensured CronLog.card_id index")
        except Exception as e:
            logger.warning(f"[Migration] Failed to create ix_cronlog_card_id: {e}")

        # StageList: OneStack → Inbound 改名
        renamed = cur.execute(
            "UPDATE stagelist SET name = 'Inbound' WHERE name = 'OneStack'"
        ).rowcount
        if renamed:
            logger.info(f"[Migration] Renamed {renamed} 'OneStack' list(s) to 'Inbound'")

        # BotUser 加 access_expires_at, extra_json
        cols = [row[1] for row in cur.execute("PRAGMA table_info(botuser)").fetchall()]
        if "access_expires_at" not in cols:
            cur.execute("ALTER TABLE botuser ADD COLUMN access_expires_at DATETIME")
            logger.info("[Migration] Added 'access_expires_at' to botuser")
        if "extra_json" not in cols:
            cur.execute("ALTER TABLE botuser ADD COLUMN extra_json TEXT DEFAULT '{}'")
            logger.info("[Migration] Added 'extra_json' to botuser")

        # BotUser 加 person_id（跨平台身份分組）
        if "person_id" not in cols:
            cur.execute("ALTER TABLE botuser ADD COLUMN person_id INTEGER DEFAULT 0")
            cur.execute("UPDATE botuser SET person_id = id WHERE person_id = 0")
            cur.execute("CREATE INDEX IF NOT EXISTS ix_botuser_person_id ON botuser(person_id)")
            logger.info("[Migration] Added 'person_id' to botuser (set to self.id)")

        # BotUser 加 password_hash（網頁登入）
        if "password_hash" not in cols:
            cur.execute("ALTER TABLE botuser ADD COLUMN password_hash TEXT")
            logger.info("[Migration] Added 'password_hash' to botuser")

        # InviteCode 加 access_valid_days, owner_person_id
        tables = [row[0] for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        if "invitecode" in tables:
            cols = [row[1] for row in cur.execute("PRAGMA table_info(invitecode)").fetchall()]
            if "access_valid_days" not in cols:
                cur.execute("ALTER TABLE invitecode ADD COLUMN access_valid_days INTEGER")
                logger.info("[Migration] Added 'access_valid_days' to invitecode")
            if "owner_person_id" not in cols:
                cur.execute("ALTER TABLE invitecode ADD COLUMN owner_person_id INTEGER")
                logger.info("[Migration] Added 'owner_person_id' to invitecode")

        # Person 表：從 BotUser 遷移真人身份
        tables = [row[0] for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        if "person" not in tables:
            cur.execute("""
                CREATE TABLE person (
                    id INTEGER PRIMARY KEY,
                    display_name VARCHAR DEFAULT '',
                    description VARCHAR DEFAULT '',
                    level INTEGER DEFAULT 0,
                    default_member_id INTEGER,
                    access_expires_at DATETIME,
                    extra_json TEXT DEFAULT '{}',
                    created_at DATETIME
                )
            """)
            # 按 person_id 分組，每組建一個 Person
            cur.execute("""
                INSERT INTO person (id, display_name, level, default_member_id, access_expires_at, extra_json, created_at)
                SELECT
                    person_id,
                    COALESCE(username, ''),
                    MAX(level),
                    MAX(default_member_id),
                    MAX(access_expires_at),
                    MAX(CASE WHEN extra_json != '{}' AND extra_json IS NOT NULL THEN extra_json ELSE '{}' END),
                    MIN(created_at)
                FROM botuser
                WHERE person_id > 0
                GROUP BY person_id
            """)
            person_count = cur.execute("SELECT COUNT(*) FROM person").fetchone()[0]
            logger.info(f"[Migration] Created 'person' table with {person_count} records from botuser")

            # 用 BotUserProject 的 display_name/description 回填到 Person
            cur.execute("""
                UPDATE person SET
                    display_name = COALESCE((
                        SELECT bup.display_name FROM bot_user_project bup
                        JOIN botuser bu ON bup.bot_user_id = bu.id
                        WHERE bu.person_id = person.id AND bup.display_name != ''
                        LIMIT 1
                    ), person.display_name),
                    description = COALESCE((
                        SELECT bup.description FROM bot_user_project bup
                        JOIN botuser bu ON bup.bot_user_id = bu.id
                        WHERE bu.person_id = person.id AND bup.description != ''
                        LIMIT 1
                    ), person.description)
            """)
            logger.info("[Migration] Backfilled Person display_name/description from BotUserProject")

            # InviteCode 的 owner_person_id 也回填
            cur.execute("""
                UPDATE invitecode SET owner_person_id = (
                    SELECT person_id FROM botuser WHERE person_id > 0 LIMIT 1
                ) WHERE owner_person_id IS NULL AND used_count > 0
            """)

        # PersonProject 表：從 BotUserProject 遷移（以 person_id 去重）
        if "person_project" not in tables:
            cur.execute("""
                CREATE TABLE person_project (
                    id INTEGER PRIMARY KEY,
                    person_id INTEGER NOT NULL,
                    project_id INTEGER NOT NULL,
                    display_name VARCHAR DEFAULT '',
                    description VARCHAR DEFAULT '',
                    can_view BOOLEAN DEFAULT 1,
                    can_create_card BOOLEAN DEFAULT 0,
                    can_run_task BOOLEAN DEFAULT 0,
                    can_comment BOOLEAN DEFAULT 1,
                    can_access_sensitive BOOLEAN DEFAULT 0,
                    is_default BOOLEAN DEFAULT 0,
                    created_at DATETIME,
                    created_by INTEGER,
                    UNIQUE(person_id, project_id)
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS ix_pp_person ON person_project(person_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS ix_pp_project ON person_project(project_id)")
            # 從 BotUserProject 遷移，按 person_id+project_id 去重
            cur.execute("""
                INSERT OR IGNORE INTO person_project
                    (person_id, project_id, display_name, description,
                     can_view, can_create_card, can_run_task, can_comment, can_access_sensitive,
                     is_default, created_at, created_by)
                SELECT
                    bu.person_id, bup.project_id, bup.display_name, bup.description,
                    bup.can_view, bup.can_create_card, bup.can_run_task, bup.can_comment, bup.can_access_sensitive,
                    bup.is_default, bup.created_at, bup.created_by
                FROM bot_user_project bup
                JOIN botuser bu ON bup.bot_user_id = bu.id
                WHERE bu.person_id > 0
            """)
            pp_count = cur.execute("SELECT COUNT(*) FROM person_project").fetchone()[0]
            logger.info(f"[Migration] Created 'person_project' with {pp_count} records")

        # PersonMember 表：從 BotUserMember 遷移
        if "person_member" not in tables:
            cur.execute("""
                CREATE TABLE person_member (
                    id INTEGER PRIMARY KEY,
                    person_id INTEGER NOT NULL,
                    member_id INTEGER NOT NULL,
                    is_default BOOLEAN DEFAULT 0,
                    can_switch BOOLEAN DEFAULT 1,
                    created_at DATETIME,
                    UNIQUE(person_id, member_id)
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS ix_pm_person ON person_member(person_id)")
            cur.execute("""
                INSERT OR IGNORE INTO person_member (person_id, member_id, is_default, can_switch, created_at)
                SELECT bu.person_id, bum.member_id, bum.is_default, bum.can_switch, bum.created_at
                FROM botusermember bum
                JOIN botuser bu ON bum.bot_user_id = bu.id
                WHERE bu.person_id > 0
            """)
            pm_count = cur.execute("SELECT COUNT(*) FROM person_member").fetchone()[0]
            logger.info(f"[Migration] Created 'person_member' with {pm_count} records")

        # Member 加 hook_profile 欄位
        cols = [row[1] for row in cur.execute("PRAGMA table_info(member)").fetchall()]
        if "hook_profile" not in cols:
            cur.execute("ALTER TABLE member ADD COLUMN hook_profile TEXT DEFAULT 'standard'")
            logger.info("[Migration] Added 'hook_profile' column to member (default='standard')")

        # Member 加 extra_json 欄位（存 TTS 偏好、ElevenLabs voice_id 等）
        if "extra_json" not in cols:
            cur.execute("ALTER TABLE member ADD COLUMN extra_json TEXT DEFAULT '{}'")
            logger.info("[Migration] Added 'extra_json' column to member (default='{}')")

        # Room: layout_type 一次性遷移 — 原有房間改為 "classic"（新建房間預設 "tiled"）
        if "room" in tables:
            cols = [row[1] for row in cur.execute("PRAGMA table_info(room)").fetchall()]
            if "layout_type" in cols:
                already = cur.execute(
                    "SELECT value FROM systemsetting WHERE key = 'migrated_room_layout_type_v1'"
                ).fetchone()
                if not already:
                    cur.execute("UPDATE room SET layout_type = 'classic'")
                    cur.execute(
                        "INSERT OR REPLACE INTO systemsetting (key, value) VALUES ('migrated_room_layout_type_v1', '1')"
                    )
                    logger.info("[Migration] Set all existing rooms' layout_type to 'classic'")

        # Room: 首次建立時 seed 預設房間（重新掃描確保 create_all 的表都能檢測到）
        tables = [row[0] for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        if "room" in tables:
            room_count = cur.execute("SELECT COUNT(*) FROM room").fetchone()[0]
            if room_count == 0:
                # 從 SystemSetting 讀現有 office_layout
                layout = "{}"
                try:
                    row = cur.execute("SELECT value FROM systemsetting WHERE key = 'office_layout'").fetchone()
                    if row and row[0]:
                        layout = row[0]
                except Exception:
                    pass

                from datetime import datetime, timezone
                now = datetime.now(timezone.utc).isoformat()
                cur.execute(
                    "INSERT INTO room (name, description, layout_json, position, is_active, created_at) VALUES (?, ?, ?, 0, 1, ?)",
                    ("主辦公室", "預設辦公空間", layout, now)
                )
                room_id = cur.lastrowid

                # 所有 active 專案加入房間（單條 INSERT...SELECT）
                cur.execute(
                    "INSERT OR IGNORE INTO roomproject (room_id, project_id) SELECT ?, id FROM project WHERE is_active = 1",
                    (room_id,)
                )

                # 所有成員加入房間（desk_index 需要 enumerate，用 executemany）
                members = cur.execute("SELECT id FROM member").fetchall()
                cur.executemany(
                    "INSERT OR IGNORE INTO roommember (room_id, member_id, desk_index) VALUES (?, ?, ?)",
                    [(room_id, row[0], i) for i, row in enumerate(members)]
                )

                # 建立預設網域
                cur.execute(
                    "INSERT INTO domain (hostname, name, room_ids_json, is_default, is_active, created_at) VALUES ('', ?, ?, 1, 1, ?)",
                    ("預設", f"[{room_id}]", now)
                )

                logger.info(f"[Migration] Created default room (id={room_id}) with all projects and members")

        conn.commit()
    except Exception as e:
        logger.warning(f"[Migration] {e}")
    finally:
        conn.close()

def init_db():
    """初始化資料庫與所有表格"""
    SQLModel.metadata.create_all(engine)
    _migrate_db()

def get_session():
    """依賴注入用的 Session 產生器"""
    with Session(engine) as session:
        yield session
