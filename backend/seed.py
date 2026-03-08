import sys
import shutil
from pathlib import Path
from sqlmodel import Session, select
from app.database import engine, init_db
from app.models.core import (
    Project, StageList, Card, Tag, CardTagLink,
    Member, Account, MemberAccount, CronJob,
)
from app.core.card_file import CardData, write_card, card_file_path
from app.core.member_profile import get_member_dir
from app.core.card_index import sync_card_to_index
from datetime import datetime, timezone

# 範例立繪路徑
EXAMPLE_PORTRAITS_DIR = Path(__file__).parent / "uploads" / "portraits"


def _seed_member_profiles():
    """Create member profile directories with initial soul.md and skills."""
    # 小筃 — 資深開發者
    jun_dir = get_member_dir("xiao-jun")
    (jun_dir / "soul.md").write_text(
        "# 小筃 — 資深開發者\n\n"
        "## 身份\n"
        "你是 Aegis AI 開發團隊的資深全端工程師「小筃」。\n\n"
        "## 專長\n"
        "- Vue 3 Composition API + TypeScript\n"
        "- Python FastAPI 後端\n"
        "- 系統架構設計\n\n"
        "## 工作風格\n"
        "- 先讀現有程式碼再動手\n"
        "- 小步提交、單一責任\n"
        "- 繁體中文註解與 commit message\n"
        "- 不自作主張加功能\n",
        encoding="utf-8",
    )
    (jun_dir / "skills" / "fullstack-dev.md").write_text(
        "# 全端開發規範\n\n"
        "- 前端使用 Vue 3 Composition API + <script setup>\n"
        "- 後端使用 FastAPI + SQLModel\n"
        "- API 路由放在 app/api/routes.py\n"
        "- 新功能要加測試\n",
        encoding="utf-8",
    )

    # 小良 — 技術主管
    liang_dir = get_member_dir("xiao-liang")
    (liang_dir / "soul.md").write_text(
        "# 小良 — 技術主管\n\n"
        "## 身份\n"
        "你是 Aegis AI 開發團隊的技術主管「小良」。\n\n"
        "## 專長\n"
        "- 需求分析與技術決策\n"
        "- Code Review\n"
        "- 架構規劃\n\n"
        "## 工作風格\n"
        "- 注重全局觀，先看整體再看細節\n"
        "- Review 時指出問題但也肯定優點\n"
        "- 決策要附帶理由\n",
        encoding="utf-8",
    )
    (liang_dir / "skills" / "code-review.md").write_text(
        "# Code Review 規範\n\n"
        "- 檢查安全性（OWASP Top 10）\n"
        "- 檢查效能瓶頸\n"
        "- 確認測試覆蓋率\n"
        "- 風格一致性\n",
        encoding="utf-8",
    )


def seed_data():
    init_db()
    with Session(engine) as session:
        if session.exec(select(Project)).first():
            print("Database already has data. Skipping seed.")
            return

        print("Seeding initial data...")

        # ── 1. Tags ──
        tags = {
            "AI-Planning": "blue",
            "AI-Coding": "purple",
            "Bug": "red",
            "Feature": "green",
            "Ops": "orange",
            "Docs": "cyan",
        }
        tag_objs = {}
        for name, color in tags.items():
            t = Tag(name=name, color=color)
            session.add(t)
            tag_objs[name] = t
        session.commit()
        for t in tag_objs.values():
            session.refresh(t)

        # ── 2. Members (AI 虛擬角色，範例) ──
        m1 = Member(
            name="小筃",
            slug="xiao-jun",
            avatar="👩‍💻",
            role="資深開發者",
            description="擅長全端開發與系統架構，負責 Coding 階段的任務執行。",
            sprite_index=0,
            portrait="/api/v1/portraits/example_1.png",
        )
        m2 = Member(
            name="小良",
            slug="xiao-liang",
            avatar="👨‍💼",
            role="技術主管",
            description="負責 Planning 與 Code Review，擅長需求分析與技術決策。",
            sprite_index=1,
            portrait="/api/v1/portraits/example_2.png",
        )
        session.add_all([m1, m2])
        session.commit()
        session.refresh(m1)
        session.refresh(m2)

        # ── 2b. Member Profile Directories ──
        _seed_member_profiles()

        # ── 3. AEGIS 系統專案（不可刪除） ──
        aegis = Project(
            name="AEGIS",
            path=str(Path(__file__).resolve().parent.parent),
            default_provider="gemini",
            is_system=True,
        )
        session.add(aegis)
        session.commit()
        session.refresh(aegis)

        # AEGIS 只有 Scheduled 列表
        aegis_scheduled = StageList(
            project_id=aegis.id, name="Scheduled", position=0
        )
        session.add(aegis_scheduled)
        session.commit()
        session.refresh(aegis_scheduled)

        # ── 4. AEGIS 系統排程（不可刪除） ──
        heartbeat_prompt = (
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
        )
        daily_report_prompt = (
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
        )

        memory_prompt = (
            "你是 Aegis 系統的記憶管理 AI。請根據以下資料整理系統記憶。\n\n"
            "## 過去 4 小時的事件\n{recent_task_logs}\n\n"
            "## 過去 4 小時的心跳報告摘要\n{recent_heartbeat_summaries}\n\n"
            "## 現有短期記憶（最近 7 天）\n{short_term_memories}\n\n"
            "## 現有長期記憶\n{long_term_memories}\n\n"
            "請執行：\n"
            "1. **短期記憶**：用 Markdown 整理這 4 小時發生的重要事實\n"
            "2. **長期記憶更新**：判斷是否有反覆出現的模式或趨勢\n\n"
            "回覆格式：\n"
            "---SHORT_TERM---\n（短期記憶內容）\n"
            "---LONG_TERM---\n（長期記憶更新，或「無需更新」）\n"
            "---LONG_TERM_FILE---\n（目標檔名，如 recurring-issues.md）"
        )

        cron_heartbeat = CronJob(
            project_id=aegis.id,
            name="心跳檢查",
            description="每 30 分鐘檢查系統狀態，判斷是否有異常需要處理。",
            prompt_template=heartbeat_prompt,
            cron_expression="*/30 * * * *",
            is_enabled=True,
            is_system=True,
        )
        cron_daily = CronJob(
            project_id=aegis.id,
            name="每日狀態報告",
            description="每天早上 9 點產出昨日任務摘要與 Token 消耗分析。",
            prompt_template=daily_report_prompt,
            cron_expression="0 9 * * *",
            is_enabled=True,
            is_system=True,
        )
        cron_memory = CronJob(
            project_id=aegis.id,
            name="記憶整理",
            description="每 4 小時回顧系統事件，整理短期記憶並更新長期記憶。",
            prompt_template=memory_prompt,
            cron_expression="0 */4 * * *",
            is_enabled=True,
            is_system=True,
        )
        session.add_all([cron_heartbeat, cron_daily, cron_memory])
        session.commit()

        # ── 5. Demo 專案 ──
        p1 = Project(
            name="Aegis Demo",
            path=str(Path(__file__).resolve().parent.parent / "aegis-demo"),
            default_provider="gemini",
        )
        session.add(p1)
        session.commit()
        session.refresh(p1)

        # ── 6. StageLists ──
        stages = ["Backlog", "Planning", "Developing", "Verifying", "Done", "Aborted"]
        stage_objs = {}
        for idx, name in enumerate(stages):
            sl = StageList(project_id=p1.id, name=name, position=idx)
            # 成員指派由使用者在團隊管理頁面設定
            session.add(sl)
            stage_objs[name] = sl
        session.commit()
        for sl in stage_objs.values():
            session.refresh(sl)

        # ── 7. Cards (範例任務) ──
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

        print(f"Seed completed!")
        print(f"  - {len(tags)} tags")
        print(f"  - 2 members (with example portraits)")
        print(f"  - 1 system project (AEGIS) with 3 cron jobs")
        print(f"  - 1 demo project with {len(stages)} stages")
        print(f"  - {len(cards_data)} cards")


if __name__ == "__main__":
    seed_data()
