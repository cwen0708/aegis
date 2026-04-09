"""SyncEnforcer 整合測試 — DB 規則載入 + Card PATCH 欄位級權限控制"""
import pytest
from datetime import datetime, timezone
from pathlib import Path
from sqlmodel import Session, SQLModel, create_engine

from app.models.core import Project, Card, StageList, CardIndex
from app.models.core import SyncRule as SyncRuleModel
from app.core.card_file import CardData, write_card, read_card, card_file_path
from app.core.card_index import sync_card_to_index
from app.core.sync_matrix import (
    SyncEnforcer,
    SyncDirection,
    ConflictStrategy,
    load_registry_from_db,
)


@pytest.fixture
def db_session(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def setup_project(db_session, tmp_path):
    project_path = tmp_path / "test-project"
    cards_dir = project_path / ".aegis" / "cards"
    cards_dir.mkdir(parents=True)

    project = Project(id=1, name="Test Project", path=str(project_path))
    db_session.add(project)

    backlog = StageList(id=1, project_id=1, name="Backlog", position=0, is_ai_stage=False)
    db_session.add(backlog)
    db_session.commit()

    return {"project": project, "backlog": backlog, "project_path": project_path}


@pytest.fixture
def setup_card(db_session, setup_project):
    """建立一張測試卡片（MD + CardIndex + ORM Card）"""
    project_path = setup_project["project_path"]
    now = datetime.now(timezone.utc)

    card_data = CardData(
        id=1, list_id=1, title="Original Title",
        description="Original Desc", content="content",
        status="idle", tags=[],
        created_at=now, updated_at=now,
    )

    fpath = card_file_path(str(project_path), 1)
    fpath.parent.mkdir(parents=True, exist_ok=True)
    write_card(fpath, card_data)

    sync_card_to_index(db_session, card_data, project_id=1, file_path=str(fpath))

    orm_card = Card(
        id=1, list_id=1, title="Original Title",
        description="Original Desc", status="idle",
        created_at=now, updated_at=now,
    )
    db_session.add(orm_card)
    db_session.commit()

    return {"card_data": card_data, "fpath": fpath}


# ==========================================================
# test_load_registry_from_db
# ==========================================================

class TestLoadRegistryFromDB:
    """確認 DB 規則正確載入為 SyncRuleRegistry"""

    def test_load_enabled_rules(self, db_session):
        """啟用的規則應正確載入並轉換。"""
        db_session.add(SyncRuleModel(
            entity_type="card", field_name="status",
            writable_by="ai", conflict_strategy="last_write_wins", is_enabled=True,
        ))
        db_session.add(SyncRuleModel(
            entity_type="card", field_name="title",
            writable_by="both", conflict_strategy="human_wins", is_enabled=True,
        ))
        db_session.commit()

        registry = load_registry_from_db(db_session)
        rule = registry.get_rule("card")
        assert rule is not None
        assert rule.entity_type == "card"
        assert len(rule.field_rules) == 2

        # status: writable_by=ai → frozenset({"ai"})
        status_fr = next(fr for fr in rule.field_rules if fr.field_name == "status")
        assert status_fr.writable_by == frozenset({"ai"})
        assert status_fr.sync_direction == SyncDirection.AI_TO_HUMAN
        assert status_fr.conflict_strategy == ConflictStrategy.LAST_WRITE_WINS

        # title: writable_by=both → frozenset({"ai", "human"})
        title_fr = next(fr for fr in rule.field_rules if fr.field_name == "title")
        assert title_fr.writable_by == frozenset({"ai", "human"})
        assert title_fr.sync_direction == SyncDirection.BIDIRECTIONAL
        assert title_fr.conflict_strategy == ConflictStrategy.LAST_WRITE_WINS

    def test_disabled_rules_excluded(self, db_session):
        """is_enabled=False 的規則不應載入。"""
        db_session.add(SyncRuleModel(
            entity_type="card", field_name="status",
            writable_by="ai", conflict_strategy="last_write_wins", is_enabled=True,
        ))
        db_session.add(SyncRuleModel(
            entity_type="card", field_name="secret",
            writable_by="human", conflict_strategy="last_write_wins", is_enabled=False,
        ))
        db_session.commit()

        registry = load_registry_from_db(db_session)
        rule = registry.get_rule("card")
        assert rule is not None
        assert len(rule.field_rules) == 1
        assert rule.field_rules[0].field_name == "status"

    def test_empty_db_returns_empty_registry(self, db_session):
        """空 DB 應回傳空的 registry。"""
        registry = load_registry_from_db(db_session)
        assert registry.get_rule("card") is None
        assert registry.list_rules() == []

    def test_multiple_entity_types(self, db_session):
        """多個 entity_type 應分別建立 SyncRule。"""
        db_session.add(SyncRuleModel(
            entity_type="card", field_name="status",
            writable_by="ai", conflict_strategy="last_write_wins", is_enabled=True,
        ))
        db_session.add(SyncRuleModel(
            entity_type="project", field_name="name",
            writable_by="human", conflict_strategy="human_wins", is_enabled=True,
        ))
        db_session.commit()

        registry = load_registry_from_db(db_session)
        assert registry.get_rule("card") is not None
        assert registry.get_rule("project") is not None
        assert len(registry.list_rules()) == 2

    def test_writable_by_human_direction(self, db_session):
        """writable_by='human' → SyncDirection.HUMAN_TO_AI"""
        db_session.add(SyncRuleModel(
            entity_type="card", field_name="description",
            writable_by="human", conflict_strategy="last_write_wins", is_enabled=True,
        ))
        db_session.commit()

        registry = load_registry_from_db(db_session)
        rule = registry.get_rule("card")
        assert rule.field_rules[0].sync_direction == SyncDirection.HUMAN_TO_AI
        assert rule.field_rules[0].writable_by == frozenset({"human"})


# ==========================================================
# Card PATCH + SyncEnforcer 整合測試
# ==========================================================

class TestPatchCardSyncEnforcement:
    """模擬 PATCH /cards/{card_id} 的 SyncEnforcer 邏輯"""

    @staticmethod
    def _apply_patch(db_session, card_id, update_fields: dict, actor: str, fpath: Path):
        """模擬 cards.py update_card 中的 SyncEnforcer 邏輯"""
        registry = load_registry_from_db(db_session)
        enforcer = SyncEnforcer(registry)

        metadata_fields = {"tags", "max_rounds", "acceptance_criteria"}
        sync_changes = {k: v for k, v in update_fields.items() if k not in metadata_fields}
        metadata_changes = {k: v for k, v in update_fields.items() if k in metadata_fields}

        result = enforcer.validate("card", sync_changes, actor)
        approved = {**result.approved, **metadata_changes}

        # 套用到 MD
        cd = read_card(fpath)
        for field_name, value in approved.items():
            if hasattr(cd, field_name):
                setattr(cd, field_name, value)
        cd.updated_at = datetime.now(timezone.utc)
        write_card(fpath, cd)

        # 套用到 ORM
        orm_card = db_session.get(Card, card_id)
        if orm_card:
            for field_name in ("status", "title", "description", "content"):
                if field_name in approved:
                    setattr(orm_card, field_name, approved[field_name])
            orm_card.updated_at = cd.updated_at
            db_session.add(orm_card)

        db_session.commit()
        return result

    def test_patch_card_ai_can_write_status(self, db_session, setup_project, setup_card):
        """actor=ai 可以更改 status（writable_by=ai）"""
        db_session.add(SyncRuleModel(
            entity_type="card", field_name="status",
            writable_by="ai", conflict_strategy="last_write_wins", is_enabled=True,
        ))
        db_session.commit()

        fpath = setup_card["fpath"]
        result = self._apply_patch(db_session, 1, {"status": "running"}, "ai", fpath)

        assert "status" in result.approved
        assert len(result.rejected) == 0

        # 驗證 MD 和 ORM 都已更新
        cd = read_card(fpath)
        assert cd.status == "running"

        orm_card = db_session.get(Card, 1)
        assert orm_card.status == "running"

    def test_patch_card_human_cannot_write_status(self, db_session, setup_project, setup_card):
        """actor=human 不能更改 status（writable_by=ai）"""
        db_session.add(SyncRuleModel(
            entity_type="card", field_name="status",
            writable_by="ai", conflict_strategy="last_write_wins", is_enabled=True,
        ))
        db_session.commit()

        fpath = setup_card["fpath"]
        result = self._apply_patch(db_session, 1, {"status": "running"}, "human", fpath)

        assert "status" not in result.approved
        assert len(result.rejected) == 1
        assert result.rejected[0].field_name == "status"

        # 驗證 status 沒有被更改
        cd = read_card(fpath)
        assert cd.status == "idle"

        orm_card = db_session.get(Card, 1)
        assert orm_card.status == "idle"

    def test_patch_card_human_can_write_title(self, db_session, setup_project, setup_card):
        """actor=human 可以更改 title（writable_by=both）"""
        db_session.add(SyncRuleModel(
            entity_type="card", field_name="title",
            writable_by="both", conflict_strategy="last_write_wins", is_enabled=True,
        ))
        db_session.commit()

        fpath = setup_card["fpath"]
        result = self._apply_patch(db_session, 1, {"title": "New Title"}, "human", fpath)

        assert "title" in result.approved
        assert len(result.rejected) == 0

        cd = read_card(fpath)
        assert cd.title == "New Title"

        orm_card = db_session.get(Card, 1)
        assert orm_card.title == "New Title"

    def test_mixed_approved_and_rejected(self, db_session, setup_project, setup_card):
        """同時更新 status 和 title，human 只能改 title"""
        db_session.add(SyncRuleModel(
            entity_type="card", field_name="status",
            writable_by="ai", conflict_strategy="last_write_wins", is_enabled=True,
        ))
        db_session.add(SyncRuleModel(
            entity_type="card", field_name="title",
            writable_by="both", conflict_strategy="last_write_wins", is_enabled=True,
        ))
        db_session.commit()

        fpath = setup_card["fpath"]
        result = self._apply_patch(
            db_session, 1,
            {"status": "running", "title": "Updated"},
            "human", fpath,
        )

        assert "title" in result.approved
        assert "status" not in result.approved
        assert len(result.rejected) == 1

        cd = read_card(fpath)
        assert cd.title == "Updated"
        assert cd.status == "idle"

    def test_metadata_fields_bypass_sync_rules(self, db_session, setup_project, setup_card):
        """tags/max_rounds/acceptance_criteria 為 metadata，不受 SyncRule 控制"""
        db_session.add(SyncRuleModel(
            entity_type="card", field_name="status",
            writable_by="ai", conflict_strategy="last_write_wins", is_enabled=True,
        ))
        db_session.commit()

        fpath = setup_card["fpath"]
        result = self._apply_patch(
            db_session, 1,
            {"tags": ["bug"], "acceptance_criteria": "pass tests"},
            "human", fpath,
        )

        # metadata 不經過 SyncEnforcer，所以 approved/rejected 只看 sync_changes
        assert len(result.rejected) == 0

        cd = read_card(fpath)
        assert cd.tags == ["bug"]
        assert cd.acceptance_criteria == "pass tests"

    def test_no_rules_allows_all_via_default(self, db_session, setup_project, setup_card):
        """無任何 SyncRule 時，entity 不存在 registry → 全部被拒（安全預設）"""
        fpath = setup_card["fpath"]
        result = self._apply_patch(db_session, 1, {"status": "running"}, "human", fpath)

        # 無規則 → entity 不在 registry → check_field_writable returns False
        assert "status" not in result.approved
        assert len(result.rejected) == 1

        cd = read_card(fpath)
        assert cd.status == "idle"
