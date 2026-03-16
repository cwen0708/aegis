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

def _migrate_db():
    """執行必要的 schema migration（SQLite ALTER TABLE）"""
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

        # InviteCode 加 access_valid_days
        tables = [row[0] for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        if "invitecode" in tables:
            cols = [row[1] for row in cur.execute("PRAGMA table_info(invitecode)").fetchall()]
            if "access_valid_days" not in cols:
                cur.execute("ALTER TABLE invitecode ADD COLUMN access_valid_days INTEGER")
                logger.info("[Migration] Added 'access_valid_days' to invitecode")

        # Room: 首次建立時 seed 預設房間（重用上方的 tables 變數）
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
