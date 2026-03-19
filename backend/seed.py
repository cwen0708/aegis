import sys
import shutil
from pathlib import Path
from sqlmodel import Session, select
from app.database import engine, init_db
from app.models.core import (
    Project, StageList, Card, Tag, CardTagLink,
    Member, Account, MemberAccount, CronJob, SystemSetting,
)
from app.core.card_file import CardData, write_card, card_file_path
from app.core.default_office_layout import get_default_office_layout_json
from app.core.member_profile import get_member_dir
from app.core.card_index import sync_card_to_index
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from croniter import croniter


def _calculate_next_scheduled_at(cron_expression: str, tz_name: str = "Asia/Taipei") -> datetime:
    """計算下一次執行時間。Cron 表達式以使用者時區解析，返回 UTC。"""
    local_tz = ZoneInfo(tz_name)
    now_local = datetime.now(local_tz)
    cron = croniter(cron_expression, now_local)
    next_local = cron.get_next(datetime)
    if next_local.tzinfo is None:
        next_local = next_local.replace(tzinfo=local_tz)
    return next_local.astimezone(timezone.utc)

# 範例立繪路徑
EXAMPLE_PORTRAITS_DIR = Path(__file__).parent / "uploads" / "portraits"

# Seed 檔案目錄
SEEDS_DIR = Path(__file__).parent / "seeds"


def _read_seed_file(filename: str) -> str:
    """讀取 seeds/ 目錄下的 .md 檔案內容。"""
    return (SEEDS_DIR / filename).read_text(encoding="utf-8")


def _seed_member_profiles():
    """Create member profile directories with initial soul.md and skills."""
    # 愛吉絲 — Aegis AI 助理
    aegis_dir = get_member_dir("aegis")
    (aegis_dir / "soul.md").write_text(_read_seed_file("aegis_soul.md"), encoding="utf-8")
    (aegis_dir / "skills" / "smart-update.md").write_text(_read_seed_file("aegis_smart-update.md"), encoding="utf-8")

    # 小良 — 技術主管
    liang_dir = get_member_dir("xiao-liang")
    (liang_dir / "soul.md").write_text(_read_seed_file("xiao-liang_soul.md"), encoding="utf-8")
    (liang_dir / "skills" / "code-review.md").write_text(_read_seed_file("xiao-liang_code-review.md"), encoding="utf-8")
    (liang_dir / "skills" / "backlog-review.md").write_text(_read_seed_file("xiao-liang_backlog-review.md"), encoding="utf-8")
    (liang_dir / "skills" / "self-upgrade.md").write_text(_read_seed_file("xiao-liang_self-upgrade.md"), encoding="utf-8")

    # 小茵 — 自我開發分析師 / 全端工程師
    yin_dir = get_member_dir("xiao-yin")
    (yin_dir / "soul.md").write_text(_read_seed_file("xiao-yin_soul.md"), encoding="utf-8")
    (yin_dir / "skills" / "fullstack-dev.md").write_text(_read_seed_file("xiao-yin_fullstack-dev.md"), encoding="utf-8")
    (yin_dir / "skills" / "self-dev.md").write_text(_read_seed_file("xiao-yin_self-dev.md"), encoding="utf-8")

    # Shared skills（所有成員共用）
    _seed_shared_skills()


def _seed_shared_skills():
    """Create shared skills directory with team roster and collaboration protocol."""
    install_root = Path(__file__).resolve().parent.parent
    shared_dir = install_root / ".aegis" / "shared" / "skills"
    shared_dir.mkdir(parents=True, exist_ok=True)

    team_file = shared_dir / "team.md"
    if not team_file.exists():
        team_file.write_text(_read_seed_file("shared_team.md"), encoding="utf-8")

    collab_file = shared_dir / "collaboration.md"
    if not collab_file.exists():
        collab_file.write_text(_read_seed_file("shared_collaboration.md"), encoding="utf-8")

    api_file = shared_dir / "aegis-api.md"
    if not api_file.exists():
        api_file.write_text(_read_seed_file("shared_aegis-api.md"), encoding="utf-8")


def _setup_dev_directory(install_root: Path) -> Path:
    """建立自我進化用的開發目錄（與運行環境分離）。

    架構：
      install_root (.local/aegis/) — 運行環境，systemd 服務使用
      dev_dir (projects/Aegis/)    — 開發目錄，AI 任務在此修改程式碼

    Git remote 策略（Fork 友善）：
      upstream → 上游開源 repo（只讀，用於拉取更新）
      origin   → 使用者自己的 fork（可 push，用於 PR 貢獻）

    自我進化流程：
      小茵在 dev_dir 開發 → git commit → 小良審查 → 部署到 install_root
      上游更新：git fetch upstream → git merge upstream/main
      貢獻回開源：git push origin → GitHub PR 到 upstream
    """
    import subprocess

    home = Path.home()
    dev_dir = home / "projects" / "Aegis"

    if dev_dir.exists() and (dev_dir / ".git").exists():
        print(f"  - Dev directory already exists: {dev_dir}")
        return dev_dir

    # 從運行環境的 git remote 取得上游 URL
    upstream_url = "https://github.com/cwen0708/aegis.git"
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=install_root, capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            upstream_url = result.stdout.strip()
    except Exception:
        pass

    dev_dir.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            ["git", "clone", upstream_url, str(dev_dir)],
            timeout=120, check=True,
        )
        # 將 origin 改名為 upstream（上游只讀）
        # origin 留給使用者設定自己的 fork（用於 PR 貢獻）
        subprocess.run(
            ["git", "remote", "rename", "origin", "upstream"],
            cwd=dev_dir, timeout=10,
        )
        print(f"  - Cloned dev directory: {dev_dir}")
        print(f"  - Remote 'upstream' → {upstream_url}")
        print("  - To contribute: fork on GitHub, then:")
        print(f"    cd {dev_dir} && git remote add origin YOUR_FORK_URL")
    except Exception as e:
        print(f"  - Warning: Failed to clone dev directory ({e}), using install dir")
        return install_root

    # 寫入 CONTRIBUTING.md（Fork 設定 + 貢獻指引，不綁定特定 AI 工具）
    contrib_md = dev_dir / "CONTRIBUTING.md"
    if not contrib_md.exists():
        contrib_md.write_text(
            "# 貢獻指南\n\n"
            "## Git Remote 架構\n\n"
            "開發目錄使用雙 remote 策略：\n"
            "- `upstream` — 上游開源 repo（只讀，拉取更新用）\n"
            "- `origin` — 你的 fork（可 push，PR 貢獻用）\n\n"
            "## 設定你的 Fork\n\n"
            "```bash\n"
            "# 1. 在 GitHub 上 fork cwen0708/aegis\n"
            "# 2. 設定 origin\n"
            "git remote add origin https://github.com/YOUR_USERNAME/aegis.git\n"
            "```\n\n"
            "## 貢獻流程\n\n"
            "```bash\n"
            "# 開發完成後\n"
            "git add <修改的檔案>\n"
            "git commit -m 'feat: 描述改動'\n"
            "git push origin main\n"
            "# 到 GitHub 建立 Pull Request\n"
            "```\n\n"
            "## 拉取上游更新\n\n"
            "```bash\n"
            "git fetch upstream\n"
            "git merge upstream/main\n"
            "# 解決衝突（如有），然後部署到運行環境\n"
            "```\n\n"
            "## 自我進化系統\n\n"
            "Aegis 內建 AI 自我進化機制：\n"
            f"- **開發目錄**：`{dev_dir}`（AI 在此修改程式碼）\n"
            f"- **運行環境**：`{install_root}`（systemd 服務）\n"
            "- 小良（AI）審查 Backlog → 小茵（AI）開發 → 小良審查部署\n"
            "- 開發完成後的改動會 commit 在開發目錄，不會自動 push\n",
            encoding="utf-8",
        )

    return dev_dir


def _sync_system_cron_jobs(session: Session):
    """同步系統排程（可重複執行，只新增不存在的排程）"""
    # 找 AEGIS 系統專案
    aegis = session.exec(select(Project).where(Project.is_system == True)).first()
    if not aegis:
        print("  AEGIS system project not found, skipping cron sync.")
        return

    # 補建缺少的系統列表（如 Inbound）
    existing_lists = {sl.name for sl in session.exec(
        select(StageList).where(StageList.project_id == aegis.id)
    ).all()}
    for pos, list_name in enumerate(["Scheduled", "Inbound"]):
        if list_name not in existing_lists:
            session.add(StageList(
                project_id=aegis.id, name=list_name, position=pos,
                is_ai_stage=True,
            ))
            print(f"  - Added missing system list: {list_name}")
    session.commit()

    existing_crons = {c.name for c in session.exec(select(CronJob).where(CronJob.project_id == aegis.id)).all()}
    crons_to_add = []

    # 心跳檢查
    if "心跳檢查" not in existing_crons:
        cron_expr = "*/30 * * * *"
        crons_to_add.append(CronJob(
            project_id=aegis.id,
            name="心跳檢查",
            description="每 30 分鐘檢查系統狀態，判斷是否有異常需要處理。",
            prompt_template=(
                "你是 Aegis 系統的心跳檢查 AI。請根據以下系統狀態進行判斷：\n\n"
                "## 系統指標\n"
                "- CPU: {cpu_percent}%\n"
                "- RAM: {mem_percent}% (可用 {mem_available_gb} GB)\n"
                "- 運行中任務: {running_count}/{max_workstations}\n\n"
                "## 待處理卡片\n{pending_cards_summary}\n\n"
                "## 最近失敗的任務\n{recent_failures}\n\n"
                "請判斷：\n"
                "1. 系統是否健康？\n"
                "2. 是否有需要關注的異常？\n"
                "3. 是否建議暫停分派（系統過載）？\n\n"
                "以 Markdown 格式回覆，簡潔扼要。"
            ),
            cron_expression=cron_expr,
            next_scheduled_at=_calculate_next_scheduled_at(cron_expr),
            is_enabled=True,
            is_system=True,
        ))

    # 每日狀態報告
    if "每日狀態報告" not in existing_crons:
        cron_expr = "0 9 * * *"
        crons_to_add.append(CronJob(
            project_id=aegis.id,
            name="每日狀態報告",
            description="每天早上 9 點產出昨日任務摘要與 Token 消耗分析。",
            prompt_template=(
                "你是 Aegis 系統的每日報告 AI。請根據以下數據產出昨日摘要：\n\n"
                "## 昨日任務統計\n{yesterday_stats}\n\n"
                "## Token 消耗\n{token_usage_summary}\n\n"
                "## 失敗任務列表\n{failed_tasks}\n\n"
                "請產出簡潔的每日報告，包含：\n"
                "1. 任務完成率\n"
                "2. 異常事件摘要\n"
                "3. Token 成本分析\n"
                "4. 建議事項\n\n"
                "以 Markdown 格式回覆。"
            ),
            cron_expression=cron_expr,
            next_scheduled_at=_calculate_next_scheduled_at(cron_expr),
            is_enabled=True,
            is_system=True,
        ))

    # 短期記憶整理（每 4 小時）
    if "短期記憶整理" not in existing_crons:
        cron_expr = "0 */4 * * *"
        crons_to_add.append(CronJob(
            project_id=aegis.id,
            name="短期記憶整理",
            description="每 4 小時整理近期事件為短期記憶。",
            prompt_template=(
                "你是 Aegis 系統的記憶管理 AI。請根據以下資料整理短期記憶。\n\n"
                "## 過去 4 小時的事件\n{recent_task_logs}\n\n"
                "## 過去 4 小時的心跳報告摘要\n{recent_heartbeat_summaries}\n\n"
                "## 現有短期記憶\n{short_term_memories}\n\n"
                "請執行：\n"
                "1. 用 Markdown 整理這 4 小時發生的重要事實（任務結果、異常、部署等）\n"
                "2. 合併或去重與既有短期記憶重複的內容\n\n"
                "回覆格式：\n"
                "---SHORT_TERM---\n（短期記憶內容）"
            ),
            cron_expression=cron_expr,
            next_scheduled_at=_calculate_next_scheduled_at(cron_expr),
            is_enabled=True,
            is_system=True,
        ))

    # 系統更新檢查
    if "系統更新檢查" not in existing_crons:
        auto_time = session.get(SystemSetting, "auto_update_time")
        time_str = auto_time.value if auto_time else "03:00"
        hour, minute = map(int, time_str.split(":"))
        cron_expr = f"{minute} {hour} * * *"
        crons_to_add.append(CronJob(
            project_id=aegis.id,
            name="系統更新檢查",
            description="自動檢查並套用 Aegis 系統更新。",
            prompt_template=(
                "你是 Aegis 系統的更新管理 AI。請執行以下步驟：\n\n"
                "1. 呼叫 GET /api/v1/update/status 檢查更新狀態\n"
                "2. 如果 has_update=true 且 is_deployed=true，呼叫 POST /api/v1/update/apply 執行更新\n"
                "3. 如果沒有更新，回報「已是最新版本」\n"
                "4. 如果更新成功，回報新版本號\n"
                "5. 如果更新失敗，記錄錯誤訊息\n\n"
                "注意：更新過程會自動等待執行中的任務完成。"
            ),
            cron_expression=cron_expr,
            next_scheduled_at=_calculate_next_scheduled_at(cron_expr),
            is_enabled=False,  # 預設關閉
            is_system=True,
        ))

    # 長期記憶整理（每天，含短期清理）
    if "長期記憶整理" not in existing_crons:
        cron_expr = "0 4 * * *"
        crons_to_add.append(CronJob(
            project_id=aegis.id,
            name="長期記憶整理",
            description="每天凌晨將短期記憶歸納為長期記憶，並清理過期短期記憶。",
            prompt_template=(
                "你是 Aegis 系統的記憶管理 AI。請執行每日長期記憶整理。\n\n"
                "## 現有短期記憶\n{short_term_memories}\n\n"
                "## 現有長期記憶\n{long_term_memories}\n\n"
                "請執行：\n"
                "1. **歸納長期記憶**：從短期記憶中提取反覆出現的模式、趨勢、重要決策\n"
                "2. **更新長期記憶**：合併到對應的長期記憶檔案（如 recurring-issues.md）\n"
                "3. **清理短期記憶**：刪除超過保留天數（memory_short_term_days）的短期記憶檔案\n"
                "4. 回報：歸納了什麼、清理了多少檔案\n\n"
                "回覆格式：\n"
                "---LONG_TERM---\n（長期記憶更新內容，或「無需更新」）\n"
                "---LONG_TERM_FILE---\n（目標檔名）\n"
                "---CLEANUP---\n（清理結果）"
            ),
            cron_expression=cron_expr,
            next_scheduled_at=_calculate_next_scheduled_at(cron_expr),
            is_enabled=True,
            is_system=True,
        ))

    # Email 分類轉發（Inbound 列表）
    if "Email 分類轉發" not in existing_crons:
        cron_expr = "*/15 * * * *"
        crons_to_add.append(CronJob(
            project_id=aegis.id,
            name="Email 分類轉發",
            description="分類未處理 email，actionable 信件轉發到 Inbound。",
            prompt_template=(
                "你是 Aegis 郵件助手。以下是 {unclassified_email_count} 封未分類的郵件：\n\n"
                "{unclassified_emails}\n\n"
                "請執行以下步驟：\n\n"
                "1. 對每封郵件分類（category: actionable/informational/spam/newsletter）\n"
                "2. 評估緊急程度（urgency: high/medium/low）\n"
                "3. 產生 1-3 句摘要\n"
                "4. 呼叫 Aegis API 批次更新分類結果：\n"
                "   POST http://localhost:8899/api/v1/emails/classify-batch\n"
                "   Content-Type: application/json\n"
                '   Body: [{{"id": <ID>, "category": "...", "urgency": "...", "summary": "...", "suggested_action": "..."}}]\n\n'
                "5. 若有 actionable 且 urgency 為 high 或 medium 的郵件，\n"
                "   且 OneStack 已設定（endpoint: {onestack_endpoint}，owner_id: {onestack_owner_id}），\n"
                "   則呼叫 OneStack Edge Function 轉發：\n"
                "   POST {onestack_endpoint}\n"
                "   Content-Type: application/json\n"
                '   Body: {{\n'
                '     "owner_id": "{onestack_owner_id}",\n'
                '     "type": "email",\n'
                '     "title": "[Email] <subject>",\n'
                '     "summary": "<摘要>",\n'
                '     "from": "<sender>",\n'
                '     "urgency": "<high|medium>",\n'
                '     "suggested_action": "<建議動作>",\n'
                '     "source_id": <email_id>\n'
                "   }}\n\n"
                "如果沒有需要分類的郵件，回覆「無待分類郵件」。\n"
                "如果 onestack_endpoint 或 onestack_owner_id 為空，跳過步驟 5。"
            ),
            cron_expression=cron_expr,
            next_scheduled_at=_calculate_next_scheduled_at(cron_expr),
            is_enabled=False,  # 需設定 Email 頻道後手動啟用
            is_system=True,
            metadata_json='{"target_list": "Inbound"}',
        ))

    # Backlog 審查與任務分派（小良 → 小茵）
    if "Backlog 審查與任務分派" not in existing_crons:
        # 找小良的收件匣 list_id
        liang_member = session.exec(select(Member).where(Member.slug == "xiao-liang")).first()
        liang_inbox = None
        if liang_member:
            liang_inbox = session.exec(
                select(StageList).where(
                    StageList.project_id == aegis.id,
                    StageList.member_id == liang_member.id,
                )
            ).first()

        cron_expr = "15 */4 * * *"  # 錯開整點，避免與其他排程撞
        crons_to_add.append(CronJob(
            project_id=aegis.id,
            name="Backlog 審查與任務分派",
            description="小良每天深夜審查 AEGIS Backlog，挑選適合的卡片規劃後分派給小茵開發。",
            prompt_template=(
                "請執行 Backlog 審查：\n\n"
                "1. 掃描 AEGIS 專案 Backlog 中所有 idle 狀態的卡片標題\n"
                "2. 跳過標題已含 [reviewed] 或 [blocked] 的卡片\n"
                "3. 根據優先順序選出 1 張最適合的卡片\n"
                "4. 深入閱讀程式碼，進行修改規劃\n"
                "5. 將規劃好的卡片分派給小茵（xiao-yin）\n"
                "6. 不適合的卡片標記 [reviewed]\n\n"
                "請參考你的 backlog-review skill 執行。"
            ),
            cron_expression=cron_expr,
            next_scheduled_at=_calculate_next_scheduled_at(cron_expr),
            is_enabled=True,
            is_system=True,
            target_list_id=liang_inbox.id if liang_inbox else None,
        ))

    if crons_to_add:
        session.add_all(crons_to_add)
        session.commit()
        print(f"  - Added {len(crons_to_add)} system cron jobs: {[c.name for c in crons_to_add]}")
    else:
        print("  - All system cron jobs already exist.")


def seed_data():
    init_db()
    with Session(engine) as session:
        has_existing_data = session.exec(select(Project)).first() is not None

        if has_existing_data:
            print("Database has existing data. Syncing system cron jobs...")
            _sync_system_cron_jobs(session)
            print("Sync completed!")
            return

        print("Seeding initial data...")

        # ── 1. Tags（跳過已存在）──
        tags = {
            "AI-Planning": "blue",
            "AI-Coding": "purple",
            "Bug": "red",
            "Feature": "green",
            "Ops": "orange",
            "Docs": "cyan",
        }
        tag_objs = {}
        existing_tags = {t.name: t for t in session.exec(select(Tag)).all()}
        added_tags = 0
        for name, color in tags.items():
            if name in existing_tags:
                tag_objs[name] = existing_tags[name]
            else:
                t = Tag(name=name, color=color)
                session.add(t)
                tag_objs[name] = t
                added_tags += 1
        if added_tags:
            session.commit()
            for t in tag_objs.values():
                session.refresh(t)
            print(f"  - Added {added_tags} tags")

        # ── 2. Members（跳過已存在）──
        existing_members = {m.slug: m for m in session.exec(select(Member)).all()}
        members_to_add = []

        if "aegis" not in existing_members:
            m_aegis = Member(
                name="愛吉絲",
                slug="aegis",
                avatar="🤖",
                role="Aegis AI 助理",
                description="Aegis 系統的預設 AI 助理，負責回答問題與協助任務管理。",
                sprite_index=0,
                portrait="/api/v1/portraits/aegis_v2.png",
            )
            members_to_add.append(m_aegis)

        if "xiao-liang" not in existing_members:
            m1 = Member(
                name="小良",
                slug="xiao-liang",
                avatar="👨‍💼",
                role="技術主管",
                description="負責 Planning 與 Code Review，擅長需求分析與技術決策。",
                sprite_index=1,
                portrait="/api/v1/portraits/example_2_v2.png",
            )
            members_to_add.append(m1)

        if "xiao-yin" not in existing_members:
            m2 = Member(
                name="小茵",
                slug="xiao-yin",
                avatar="👩‍💻",
                role="自我開發分析師 / 全端工程師",
                description="負責 Aegis 自我進化開發，擅長全端開發與程式碼品質分析。",
                sprite_index=2,
                portrait="/api/v1/portraits/example_1_v2.png",
            )
            members_to_add.append(m2)

        if members_to_add:
            session.add_all(members_to_add)
            session.commit()
            for m in members_to_add:
                session.refresh(m)
            print(f"  - Added {len(members_to_add)} members")

        # ── 2b. Member Profile Directories ──
        _seed_member_profiles()

        # ── 2c. 管理員密碼（跳過已存在）──
        if not session.get(SystemSetting, "admin_password"):
            from app.core.auth import hash_password, DEFAULT_PASSWORD
            session.add(SystemSetting(key="admin_password", value=hash_password(DEFAULT_PASSWORD)))
            print("  - Added admin_password setting (hashed default)")

        # ── 2d. 預設辦公室佈局（跳過已存在）──
        if not session.get(SystemSetting, "office_layout"):
            office_layout_setting = SystemSetting(
                key="office_layout",
                value=get_default_office_layout_json()
            )
            session.add(office_layout_setting)
            print("  - Added office_layout setting")

        # ── 2d. OneStack 設定（跳過已存在）──
        if not session.get(SystemSetting, "onestack_owner_id"):
            session.add(SystemSetting(key="onestack_owner_id", value=""))
            print("  - Added onestack_owner_id setting (empty)")
        if not session.get(SystemSetting, "onestack_endpoint"):
            session.add(SystemSetting(key="onestack_endpoint", value="https://avioqoteujivjkpnvyyo.supabase.co/functions/v1/receive-suggestion"))
            print("  - Added onestack_endpoint setting")

        # ── 2e. 管理員設定（跳過已存在）──
        import os
        admin_ids = os.getenv("AEGIS_ADMIN_USER_IDS", "")
        if admin_ids and not session.get(SystemSetting, "admin_user_ids"):
            admin_setting = SystemSetting(
                key="admin_user_ids",
                value=admin_ids
            )
            session.add(admin_setting)
            print(f"  - Admin user IDs configured: {admin_ids}")

        session.commit()

        # ── 3. AEGIS 系統專案（跳過已存在）──
        aegis = session.exec(select(Project).where(Project.name == "AEGIS")).first()
        if not aegis:
            # 自我進化架構：開發目錄 (git clone) 與運行環境 (.local) 分離
            install_root = Path(__file__).resolve().parent.parent
            dev_dir = _setup_dev_directory(install_root)

            aegis = Project(
                name="AEGIS",
                path=str(dev_dir),
                default_provider="gemini",
                is_system=True,
            )
            session.add(aegis)
            session.commit()
            session.refresh(aegis)
            print(f"  - Added AEGIS system project (dev: {dev_dir})")

            # AEGIS 系統列表
            for pos, list_name in enumerate(["Scheduled", "Inbound"]):
                sl = StageList(
                    project_id=aegis.id,
                    name=list_name,
                    position=pos,
                    is_ai_stage=True,
                )
                session.add(sl)
            session.commit()

        # ── 4. AEGIS 系統排程 ──
        _sync_system_cron_jobs(session)

        # ── 5. Demo 專案（跳過已存在）──
        p1 = session.exec(select(Project).where(Project.name == "Aegis Demo")).first()
        if not p1:
            p1 = Project(
                name="Aegis Demo",
                path=str(Path(__file__).resolve().parent.parent / "projects" / "aegis-demo"),
                default_provider="gemini",
            )
            session.add(p1)
            session.commit()
            session.refresh(p1)
            print("  - Added Aegis Demo project")

            # ── 6. StageLists ──
            # (name, is_ai_stage)
            stages_config = [
                ("Backlog", False),
                ("Planning", True),
                ("Developing", True),
                ("Verifying", True),
                ("Done", False),
                ("Aborted", False),
            ]
            stage_objs = {}
            for idx, (name, is_ai) in enumerate(stages_config):
                sl = StageList(
                    project_id=p1.id,
                    name=name,
                    position=idx,
                    is_ai_stage=is_ai,
                )
                session.add(sl)
                stage_objs[name] = sl
            session.commit()
            for sl in stage_objs.values():
                session.refresh(sl)
            print(f"  - Added {len(stage_objs)} stage lists")

            # ── 7. Cards（只在新建 Demo 專案時加入）──
            cards_data = [
                {
                    "list": "Developing",
                    "title": "實作漢諾塔演算法",
                    "description": "用 Python 實作經典的漢諾塔 (Tower of Hanoi) 遞迴解法，包含視覺化輸出。",
                    "content": "## 目標\n\n實作漢諾塔 (Tower of Hanoi) 演算法。\n\n## 需求\n\n1. 使用遞迴方式實作\n2. 支援任意數量的盤子 (n)\n3. 印出每一步的移動過程\n4. 加上步數計算與驗證 (應為 2^n - 1 步)\n\n## 範例輸出\n\n```\nMove disk 1 from A to C\nMove disk 2 from A to B\nMove disk 1 from C to B\nMove disk 3 from A to C\nMove disk 1 from B to A\nMove disk 2 from B to C\nMove disk 1 from A to C\nTotal moves: 7\n```\n\n## 驗收標準\n\n- [ ] 遞迴實作正確\n- [ ] 支援 n=1 到 n=10\n- [ ] 輸出格式清晰\n- [ ] 包含單元測試",
                    "tags": ["AI-Coding"],
                    "status": "pending",
                },
            ]

            for cd in cards_data:
                card = Card(
                    list_id=stage_objs[cd["list"]].id,
                    title=cd["title"],
                    description=cd["description"],
                    content=cd.get("content", ""),
                    status=cd.get("status", "idle"),
                )
                session.add(card)
                session.commit()
                session.refresh(card)

                # 建立 tag 關聯
                for tag_name in cd.get("tags", []):
                    session.add(CardTagLink(card_id=card.id, tag_id=tag_objs[tag_name].id))
                session.commit()

                # 同步寫入 MD 檔 + CardIndex
                now = datetime.now(timezone.utc)
                card_data = CardData(
                    id=card.id, list_id=card.list_id, title=card.title,
                    description=card.description, content=card.content,
                    status=card.status, tags=cd.get("tags", []),
                    created_at=now, updated_at=now,
                )
                fpath = card_file_path(p1.path, card.id)
                write_card(fpath, card_data)
                sync_card_to_index(session, card_data, project_id=p1.id, file_path=str(fpath))
                session.commit()

            print(f"  - Added {len(cards_data)} cards")

        print("Seed completed!")


if __name__ == "__main__":
    seed_data()
