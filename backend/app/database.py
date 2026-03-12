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
