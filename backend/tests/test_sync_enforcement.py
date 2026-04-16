"""SyncEnforcer 整合測試 — DB 規則載入 + Card PATCH 欄位級權限控制"""
import pytest
import httpx
from datetime import datetime, timedelta, timezone
from pathlib import Path
from sqlmodel import Session, SQLModel, create_engine, select

from app.models.core import Project, Card, StageList, CardIndex
from app.models.core import SyncRule as SyncRuleModel
from app.core.card_file import CardData, write_card, read_card, card_file_path
from app.core.card_index import sync_card_to_index
from app.core.sync_matrix import (
    SyncEnforcer,
    ConflictResolver,
    FieldVersion,
    FieldRule,
    SyncDirection,
    ConflictStrategy,
    SyncRule as SyncRuleDomain,
    SyncRuleRegistry,
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

        # title: writable_by=both, conflict_strategy=human_wins → HUMAN_WINS
        title_fr = next(fr for fr in rule.field_rules if fr.field_name == "title")
        assert title_fr.writable_by == frozenset({"ai", "human"})
        assert title_fr.sync_direction == SyncDirection.BIDIRECTIONAL
        assert title_fr.conflict_strategy == ConflictStrategy.HUMAN_WINS

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


# ==========================================================
# StageList PATCH + SyncEnforcer 整合測試
# ==========================================================

class TestStageListSyncEnforcement:
    """模擬 PATCH /lists/{list_id} 的 SyncEnforcer 邏輯"""

    @staticmethod
    def _apply_patch(db_session, list_id, update_fields: dict, actor: str):
        """模擬 projects.py update_stage_list 中的 SyncEnforcer 邏輯"""
        registry = load_registry_from_db(db_session)
        enforcer = SyncEnforcer(registry)

        _METADATA_FIELDS = {
            "description", "member_id", "system_instruction",
            "prompt_template", "is_ai_stage", "on_success_action",
            "on_fail_action", "auto_commit",
        }

        sync_changes = {k: v for k, v in update_fields.items() if k not in _METADATA_FIELDS}
        metadata_changes = {k: v for k, v in update_fields.items() if k in _METADATA_FIELDS}

        result = enforcer.validate("stagelist", sync_changes, actor)
        approved = {**result.approved, **metadata_changes}

        # 套用到 ORM
        stage_list = db_session.get(StageList, list_id)
        if stage_list:
            if "name" in approved:
                stage_list.name = approved["name"]
            if "position" in approved:
                stage_list.position = approved["position"]
            db_session.add(stage_list)
        db_session.commit()
        return result

    def test_ai_change_name_rejected(self, db_session, setup_project):
        """actor=ai 不能更改 name（human_to_ai 規則，writable_by=human）"""
        db_session.add(SyncRuleModel(
            entity_type="stagelist", field_name="name",
            writable_by="human", conflict_strategy="human_wins", is_enabled=True,
        ))
        db_session.commit()

        result = self._apply_patch(db_session, 1, {"name": "AI-Renamed"}, "ai")

        assert "name" not in result.approved
        assert len(result.rejected) == 1
        assert result.rejected[0].field_name == "name"

        stage_list = db_session.get(StageList, 1)
        assert stage_list.name == "Backlog"

    def test_ai_change_position_rejected(self, db_session, setup_project):
        """actor=ai 不能更改 position（human_to_ai 規則，writable_by=human）"""
        db_session.add(SyncRuleModel(
            entity_type="stagelist", field_name="position",
            writable_by="human", conflict_strategy="human_wins", is_enabled=True,
        ))
        db_session.commit()

        result = self._apply_patch(db_session, 1, {"position": 99}, "ai")

        assert "position" not in result.approved
        assert len(result.rejected) == 1
        assert result.rejected[0].field_name == "position"

        stage_list = db_session.get(StageList, 1)
        assert stage_list.position == 0

    def test_human_change_name_approved(self, db_session, setup_project):
        """actor=human 可以更改 name（writable_by=human）"""
        db_session.add(SyncRuleModel(
            entity_type="stagelist", field_name="name",
            writable_by="human", conflict_strategy="human_wins", is_enabled=True,
        ))
        db_session.commit()

        result = self._apply_patch(db_session, 1, {"name": "Renamed"}, "human")

        assert "name" in result.approved
        assert len(result.rejected) == 0

        stage_list = db_session.get(StageList, 1)
        assert stage_list.name == "Renamed"

    def test_mixed_approved_and_rejected(self, db_session, setup_project):
        """AI 送多欄位：name 被拒、position 被拒、description 通過（metadata）"""
        db_session.add(SyncRuleModel(
            entity_type="stagelist", field_name="name",
            writable_by="human", conflict_strategy="human_wins", is_enabled=True,
        ))
        db_session.add(SyncRuleModel(
            entity_type="stagelist", field_name="position",
            writable_by="human", conflict_strategy="human_wins", is_enabled=True,
        ))
        db_session.commit()

        result = self._apply_patch(
            db_session, 1,
            {"name": "AI-Name", "position": 5, "description": "AI desc"},
            "ai",
        )

        # name 和 position 被拒
        assert "name" not in result.approved
        assert "position" not in result.approved
        assert len(result.rejected) == 2

        # description 是 metadata，不經 SyncEnforcer，直接通過
        stage_list = db_session.get(StageList, 1)
        assert stage_list.name == "Backlog"
        assert stage_list.position == 0


# ==========================================================
# ConflictResolver + DB 規則整合測試
# ==========================================================

class TestConflictResolverIntegration:
    """ConflictResolver 整合測試 — 結合 DB 規則載入與卡片 MD 資料"""

    @staticmethod
    def _resolve_with_db(db_session, entity_type, local_changes, remote_changes):
        """從 DB 載入 registry，建立 ConflictResolver 並執行解決"""
        registry = load_registry_from_db(db_session)
        resolver = ConflictResolver(registry)
        return resolver.resolve(entity_type, local_changes, remote_changes)

    def test_conflict_resolve_lww_auto(self, db_session, setup_project, setup_card):
        """LWW 策略：local 較新自動解決，remote 較舊被覆蓋"""
        # 設定 title 為 LWW 策略
        db_session.add(SyncRuleModel(
            entity_type="card", field_name="title",
            writable_by="both", conflict_strategy="last_write_wins", is_enabled=True,
        ))
        db_session.commit()

        fpath = setup_card["fpath"]
        cd = read_card(fpath)

        # local 時間戳必須比 card 的 updated_at 還新
        from datetime import timedelta
        local_ts = cd.updated_at + timedelta(hours=1)

        local = {
            "title": FieldVersion("Local Title", local_ts, "human"),
        }
        # remote 使用卡片 MD 的 updated_at
        remote = {
            "title": FieldVersion(cd.title, cd.updated_at, "remote"),
        }

        result = self._resolve_with_db(db_session, "card", local, remote)

        assert len(result.resolved) == 1
        assert result.resolved[0].field_name == "title"
        assert result.resolved[0].value == "Local Title"
        assert result.resolved[0].strategy == ConflictStrategy.LAST_WRITE_WINS
        assert len(result.deferred) == 0

    def test_conflict_resolve_manual_merge_deferred(self, db_session, setup_project, setup_card):
        """MANUAL_MERGE 策略：雙方都有變更時進入 deferred"""
        # 設定 description 為 manual_merge 策略
        db_session.add(SyncRuleModel(
            entity_type="card", field_name="description",
            writable_by="both", conflict_strategy="manual_merge", is_enabled=True,
        ))
        db_session.commit()

        fpath = setup_card["fpath"]
        cd = read_card(fpath)

        local = {
            "description": FieldVersion("Local Desc", datetime(2026, 4, 2, tzinfo=timezone.utc), "human"),
        }
        remote = {
            "description": FieldVersion(cd.description, cd.updated_at, "remote"),
        }

        result = self._resolve_with_db(db_session, "card", local, remote)

        assert len(result.resolved) == 0
        assert len(result.deferred) == 1
        assert result.deferred[0].field_name == "description"
        assert result.deferred[0].strategy == ConflictStrategy.MANUAL_MERGE
        assert result.deferred[0].local.value == "Local Desc"
        assert result.deferred[0].remote.value == cd.description

    def test_conflict_resolve_local_only(self, db_session, setup_project, setup_card):
        """單方變更（只有 local）：無衝突，直接 resolve"""
        db_session.add(SyncRuleModel(
            entity_type="card", field_name="title",
            writable_by="both", conflict_strategy="last_write_wins", is_enabled=True,
        ))
        db_session.commit()

        local = {
            "title": FieldVersion("New Title", datetime(2026, 4, 2, tzinfo=timezone.utc), "human"),
        }
        # remote 無變更
        remote: dict[str, FieldVersion] = {}

        result = self._resolve_with_db(db_session, "card", local, remote)

        assert len(result.resolved) == 1
        assert result.resolved[0].field_name == "title"
        assert result.resolved[0].value == "New Title"
        assert len(result.deferred) == 0


# ==========================================================
# load_registry_from_db — ai_merge 策略映射修正
# ==========================================================

class TestStrategyMapping:
    """確認 DB conflict_strategy 正確映射為 ConflictStrategy enum"""

    def test_ai_merge_maps_to_ai_merge_enum(self, db_session):
        """ai_merge 應映射為 ConflictStrategy.AI_MERGE，而非 MANUAL_MERGE。"""
        db_session.add(SyncRuleModel(
            entity_type="card", field_name="content",
            writable_by="both", conflict_strategy="ai_merge", is_enabled=True,
        ))
        db_session.commit()

        registry = load_registry_from_db(db_session)
        rule = registry.get_rule("card")
        assert rule is not None
        fr = rule.field_rules[0]
        assert fr.conflict_strategy == ConflictStrategy.AI_MERGE

    def test_manual_merge_maps_to_manual_merge_enum(self, db_session):
        """manual_merge 應映射為 ConflictStrategy.MANUAL_MERGE。"""
        db_session.add(SyncRuleModel(
            entity_type="card", field_name="description",
            writable_by="both", conflict_strategy="manual_merge", is_enabled=True,
        ))
        db_session.commit()

        registry = load_registry_from_db(db_session)
        rule = registry.get_rule("card")
        fr = rule.field_rules[0]
        assert fr.conflict_strategy == ConflictStrategy.MANUAL_MERGE

    def test_all_strategies_mapped_correctly(self, db_session):
        """所有策略值都應正確映射。"""
        strategies = [
            ("last_write_wins", ConflictStrategy.LAST_WRITE_WINS),
            ("human_wins", ConflictStrategy.HUMAN_WINS),
            ("ai_wins", ConflictStrategy.AI_WINS),
            ("manual_merge", ConflictStrategy.MANUAL_MERGE),
            ("ai_merge", ConflictStrategy.AI_MERGE),
        ]
        for i, (db_val, expected) in enumerate(strategies):
            db_session.add(SyncRuleModel(
                entity_type=f"entity_{i}", field_name="field",
                writable_by="both", conflict_strategy=db_val, is_enabled=True,
            ))
        db_session.commit()

        registry = load_registry_from_db(db_session)
        for i, (db_val, expected) in enumerate(strategies):
            rule = registry.get_rule(f"entity_{i}")
            assert rule is not None, f"entity_{i} should exist"
            assert rule.field_rules[0].conflict_strategy == expected, (
                f"{db_val} should map to {expected}"
            )

    def test_human_wins_maps_to_human_wins_enum(self, db_session):
        """human_wins 應映射為 ConflictStrategy.HUMAN_WINS。"""
        db_session.add(SyncRuleModel(
            entity_type="card", field_name="priority",
            writable_by="both", conflict_strategy="human_wins", is_enabled=True,
        ))
        db_session.commit()

        registry = load_registry_from_db(db_session)
        rule = registry.get_rule("card")
        assert rule is not None
        fr = rule.field_rules[0]
        assert fr.conflict_strategy == ConflictStrategy.HUMAN_WINS

    def test_ai_wins_maps_to_ai_wins_enum(self, db_session):
        """ai_wins 應映射為 ConflictStrategy.AI_WINS。"""
        db_session.add(SyncRuleModel(
            entity_type="card", field_name="source",
            writable_by="both", conflict_strategy="ai_wins", is_enabled=True,
        ))
        db_session.commit()

        registry = load_registry_from_db(db_session)
        rule = registry.get_rule("card")
        assert rule is not None
        fr = rule.field_rules[0]
        assert fr.conflict_strategy == ConflictStrategy.AI_WINS


class TestLoadRegistrySyncDirection:
    """確認 DB sync_direction 欄位正確載入並覆蓋 writable_by 推導"""

    def test_explicit_sync_direction_overrides_writable_by(self, db_session):
        """sync_direction='read_only' 應覆蓋 writable_by='both' 的推導"""
        db_session.add(SyncRuleModel(
            entity_type="card", field_name="locked_field",
            writable_by="both", sync_direction="read_only",
            conflict_strategy="last_write_wins", is_enabled=True,
        ))
        db_session.commit()

        registry = load_registry_from_db(db_session)
        rule = registry.get_rule("card")
        assert rule is not None
        fr = rule.field_rules[0]
        assert fr.sync_direction == SyncDirection.READ_ONLY

    def test_none_sync_direction_falls_back_to_writable_by(self, db_session):
        """sync_direction=None 應從 writable_by='ai' 推導為 AI_TO_HUMAN"""
        db_session.add(SyncRuleModel(
            entity_type="card", field_name="status",
            writable_by="ai", sync_direction=None,
            conflict_strategy="last_write_wins", is_enabled=True,
        ))
        db_session.commit()

        registry = load_registry_from_db(db_session)
        rule = registry.get_rule("card")
        assert rule is not None
        fr = rule.field_rules[0]
        assert fr.sync_direction == SyncDirection.AI_TO_HUMAN

    def test_explicit_bidirectional_with_ai_writable(self, db_session):
        """sync_direction='bidirectional' + writable_by='ai' → BIDIRECTIONAL（sync_direction 優先）"""
        db_session.add(SyncRuleModel(
            entity_type="card", field_name="notes",
            writable_by="ai", sync_direction="bidirectional",
            conflict_strategy="last_write_wins", is_enabled=True,
        ))
        db_session.commit()

        registry = load_registry_from_db(db_session)
        rule = registry.get_rule("card")
        fr = rule.field_rules[0]
        assert fr.sync_direction == SyncDirection.BIDIRECTIONAL

    def test_all_four_directions(self, db_session):
        """四種 sync_direction 值都能正確映射"""
        directions = [
            ("ai_to_human", SyncDirection.AI_TO_HUMAN),
            ("human_to_ai", SyncDirection.HUMAN_TO_AI),
            ("bidirectional", SyncDirection.BIDIRECTIONAL),
            ("read_only", SyncDirection.READ_ONLY),
        ]
        for i, (db_val, _expected) in enumerate(directions):
            db_session.add(SyncRuleModel(
                entity_type=f"entity_{i}", field_name="field",
                writable_by="both", sync_direction=db_val,
                conflict_strategy="last_write_wins", is_enabled=True,
            ))
        db_session.commit()

        registry = load_registry_from_db(db_session)
        for i, (db_val, expected) in enumerate(directions):
            rule = registry.get_rule(f"entity_{i}")
            assert rule is not None
            assert rule.field_rules[0].sync_direction == expected, (
                f"{db_val} should map to {expected}"
            )

    def test_column_nullable_default(self, db_session):
        """sync_direction=None（DB 預設值）時，writable_by fallback 正常產生方向與權限。"""
        db_session.add(SyncRuleModel(
            entity_type="card", field_name="title",
            writable_by="both", conflict_strategy="last_write_wins", is_enabled=True,
        ))
        db_session.commit()

        from sqlmodel import select as sel
        db_rule = db_session.exec(
            sel(SyncRuleModel).where(SyncRuleModel.field_name == "title")
        ).first()
        assert db_rule.sync_direction is None

        registry = load_registry_from_db(db_session)
        rule = registry.get_rule("card")
        assert rule is not None
        fr = rule.field_rules[0]
        assert fr.sync_direction == SyncDirection.BIDIRECTIONAL
        assert fr.writable_by == frozenset({"ai", "human"})
        assert registry.check_field_writable("card", "title", "ai") is True
        assert registry.check_field_writable("card", "title", "human") is True


class TestConflictResolverDBStrategy:
    """ConflictResolver 整合測試 — 從 DB 載入 human_wins / ai_wins 策略並驗證解決行為"""

    @staticmethod
    def _resolve_with_db(db_session, entity_type, local_changes, remote_changes):
        registry = load_registry_from_db(db_session)
        resolver = ConflictResolver(registry)
        return resolver.resolve(entity_type, local_changes, remote_changes)

    def test_human_wins_from_db_prefers_human(self, db_session, setup_project):
        """DB human_wins 策略：human actor 的變更勝出"""
        db_session.add(SyncRuleModel(
            entity_type="card", field_name="priority",
            writable_by="both", conflict_strategy="human_wins", is_enabled=True,
        ))
        db_session.commit()

        local = {"priority": FieldVersion("High", datetime(2026, 4, 1, tzinfo=timezone.utc), "human")}
        remote = {"priority": FieldVersion("Low", datetime(2026, 4, 2, tzinfo=timezone.utc), "ai")}

        result = self._resolve_with_db(db_session, "card", local, remote)
        assert len(result.resolved) == 1
        assert result.resolved[0].value == "High"
        assert result.resolved[0].strategy == ConflictStrategy.HUMAN_WINS

    def test_ai_wins_from_db_prefers_ai(self, db_session, setup_project):
        """DB ai_wins 策略：ai actor 的變更勝出"""
        db_session.add(SyncRuleModel(
            entity_type="card", field_name="source",
            writable_by="both", conflict_strategy="ai_wins", is_enabled=True,
        ))
        db_session.commit()

        local = {"source": FieldVersion("manual", datetime(2026, 4, 2, tzinfo=timezone.utc), "human")}
        remote = {"source": FieldVersion("auto", datetime(2026, 4, 1, tzinfo=timezone.utc), "ai")}

        result = self._resolve_with_db(db_session, "card", local, remote)
        assert len(result.resolved) == 1
        assert result.resolved[0].value == "auto"
        assert result.resolved[0].strategy == ConflictStrategy.AI_WINS


# ==========================================================
# SyncRule CRUD API 端點測試
# ==========================================================

@pytest.fixture
async def api_client(tmp_path):
    """建立指向臨時 DB 的 async httpx 測試客戶端。"""
    db_path = tmp_path / "test_api.db"
    engine = create_engine(f"sqlite:///{db_path}")
    SQLModel.metadata.create_all(engine)

    from app.main import app
    from app.database import get_session

    def _override():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = _override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


class TestSyncRuleCreateAPI:
    """POST /api/v1/sync-rules 端點測試"""

    async def test_create_sync_rule(self, api_client):
        """成功建立新規則。"""
        resp = await api_client.post("/api/v1/sync-rules", json={
            "entity_type": "card",
            "field_name": "title",
            "writable_by": "both",
            "conflict_strategy": "last_write_wins",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["entity_type"] == "card"
        assert data["field_name"] == "title"
        assert data["writable_by"] == "both"
        assert data["conflict_strategy"] == "last_write_wins"
        assert data["is_enabled"] is True
        assert "id" in data

    async def test_create_duplicate_returns_409(self, api_client):
        """重複 entity_type + field_name 應回傳 409。"""
        payload = {
            "entity_type": "card",
            "field_name": "status",
            "writable_by": "ai",
            "conflict_strategy": "last_write_wins",
        }
        resp1 = await api_client.post("/api/v1/sync-rules", json=payload)
        assert resp1.status_code == 201

        resp2 = await api_client.post("/api/v1/sync-rules", json=payload)
        assert resp2.status_code == 409

    async def test_create_invalid_writable_by_returns_422(self, api_client):
        """無效 writable_by 應回傳 422。"""
        resp = await api_client.post("/api/v1/sync-rules", json={
            "entity_type": "card",
            "field_name": "title",
            "writable_by": "invalid",
        })
        assert resp.status_code == 422

    async def test_create_invalid_conflict_strategy_returns_422(self, api_client):
        """無效 conflict_strategy 應回傳 422。"""
        resp = await api_client.post("/api/v1/sync-rules", json={
            "entity_type": "card",
            "field_name": "title",
            "conflict_strategy": "invalid",
        })
        assert resp.status_code == 422

    async def test_create_with_manual_merge_strategy(self, api_client):
        """使用 manual_merge 策略建立規則。"""
        resp = await api_client.post("/api/v1/sync-rules", json={
            "entity_type": "card",
            "field_name": "description",
            "conflict_strategy": "manual_merge",
        })
        assert resp.status_code == 201
        assert resp.json()["conflict_strategy"] == "manual_merge"

    async def test_create_with_ai_merge_strategy(self, api_client):
        """使用 ai_merge 策略建立規則。"""
        resp = await api_client.post("/api/v1/sync-rules", json={
            "entity_type": "card",
            "field_name": "content",
            "conflict_strategy": "ai_merge",
        })
        assert resp.status_code == 201
        assert resp.json()["conflict_strategy"] == "ai_merge"

    async def test_created_rule_visible_in_get(self, api_client):
        """POST 建立後 GET 可查到。"""
        await api_client.post("/api/v1/sync-rules", json={
            "entity_type": "card",
            "field_name": "title",
        })

        resp = await api_client.get("/api/v1/sync-rules", params={"entity_type": "card"})
        assert resp.status_code == 200
        rules = resp.json()
        assert any(r["field_name"] == "title" for r in rules)


class TestSyncRuleDeleteAPI:
    """DELETE /api/v1/sync-rules/{rule_id} 端點測試"""

    async def test_delete_sync_rule(self, api_client):
        """成功刪除規則。"""
        create_resp = await api_client.post("/api/v1/sync-rules", json={
            "entity_type": "card",
            "field_name": "title",
        })
        rule_id = create_resp.json()["id"]

        del_resp = await api_client.delete(f"/api/v1/sync-rules/{rule_id}")
        assert del_resp.status_code == 204

    async def test_delete_nonexistent_returns_404(self, api_client):
        """刪除不存在的規則應回傳 404。"""
        resp = await api_client.delete("/api/v1/sync-rules/99999")
        assert resp.status_code == 404

    async def test_deleted_rule_not_in_get(self, api_client):
        """DELETE 刪除後 GET 不再回傳。"""
        create_resp = await api_client.post("/api/v1/sync-rules", json={
            "entity_type": "card",
            "field_name": "title",
        })
        rule_id = create_resp.json()["id"]

        await api_client.delete(f"/api/v1/sync-rules/{rule_id}")

        get_resp = await api_client.get("/api/v1/sync-rules", params={"entity_type": "card"})
        rules = get_resp.json()
        assert not any(r["id"] == rule_id for r in rules)


class TestSyncRuleUpdateStrategyAPI:
    """PUT /api/v1/sync-rules/{rule_id} — manual_merge / ai_merge 策略更新"""

    async def test_update_to_manual_merge(self, api_client):
        """PUT 設定 manual_merge 策略成功。"""
        create_resp = await api_client.post("/api/v1/sync-rules", json={
            "entity_type": "card",
            "field_name": "title",
            "conflict_strategy": "last_write_wins",
        })
        rule_id = create_resp.json()["id"]

        put_resp = await api_client.put(f"/api/v1/sync-rules/{rule_id}", json={
            "conflict_strategy": "manual_merge",
        })
        assert put_resp.status_code == 200
        assert put_resp.json()["conflict_strategy"] == "manual_merge"

    async def test_update_to_ai_merge(self, api_client):
        """PUT 設定 ai_merge 策略成功。"""
        create_resp = await api_client.post("/api/v1/sync-rules", json={
            "entity_type": "card",
            "field_name": "title",
            "conflict_strategy": "last_write_wins",
        })
        rule_id = create_resp.json()["id"]

        put_resp = await api_client.put(f"/api/v1/sync-rules/{rule_id}", json={
            "conflict_strategy": "ai_merge",
        })
        assert put_resp.status_code == 200
        assert put_resp.json()["conflict_strategy"] == "ai_merge"


class TestSyncDirectionAPI:
    """POST / PUT / GET sync_direction 欄位的 CRUD 測試"""

    async def test_create_with_sync_direction(self, api_client):
        """POST 指定 sync_direction=read_only 成功建立。"""
        resp = await api_client.post("/api/v1/sync-rules", json={
            "entity_type": "card",
            "field_name": "locked",
            "writable_by": "both",
            "sync_direction": "read_only",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["sync_direction"] == "read_only"

    async def test_create_without_sync_direction_returns_none(self, api_client):
        """POST 不指定 sync_direction 時回傳 None（向後相容）。"""
        resp = await api_client.post("/api/v1/sync-rules", json={
            "entity_type": "card",
            "field_name": "title",
        })
        assert resp.status_code == 201
        assert resp.json()["sync_direction"] is None

    async def test_create_invalid_sync_direction_returns_422(self, api_client):
        """POST 無效 sync_direction 應回傳 422。"""
        resp = await api_client.post("/api/v1/sync-rules", json={
            "entity_type": "card",
            "field_name": "title",
            "sync_direction": "invalid_direction",
        })
        assert resp.status_code == 422

    async def test_get_returns_sync_direction(self, api_client):
        """GET 回傳含 sync_direction 欄位。"""
        await api_client.post("/api/v1/sync-rules", json={
            "entity_type": "card",
            "field_name": "content",
            "sync_direction": "ai_to_human",
        })
        resp = await api_client.get("/api/v1/sync-rules", params={"entity_type": "card"})
        assert resp.status_code == 200
        rules = resp.json()
        content_rule = next(r for r in rules if r["field_name"] == "content")
        assert content_rule["sync_direction"] == "ai_to_human"

    async def test_update_sync_direction(self, api_client):
        """PUT 更新 sync_direction 成功。"""
        create_resp = await api_client.post("/api/v1/sync-rules", json={
            "entity_type": "card",
            "field_name": "desc",
            "sync_direction": "bidirectional",
        })
        rule_id = create_resp.json()["id"]

        put_resp = await api_client.put(f"/api/v1/sync-rules/{rule_id}", json={
            "sync_direction": "human_to_ai",
        })
        assert put_resp.status_code == 200
        assert put_resp.json()["sync_direction"] == "human_to_ai"

    async def test_update_invalid_sync_direction_returns_422(self, api_client):
        """PUT 無效 sync_direction 應回傳 422。"""
        create_resp = await api_client.post("/api/v1/sync-rules", json={
            "entity_type": "card",
            "field_name": "notes",
        })
        rule_id = create_resp.json()["id"]

        put_resp = await api_client.put(f"/api/v1/sync-rules/{rule_id}", json={
            "sync_direction": "bad_value",
        })
        assert put_resp.status_code == 422


# ==========================================================
# GET /sync-rules/{entity_type} 端點測試
# ==========================================================

class TestSyncRuleGetByEntityAPI:
    """GET /sync-rules/{entity_type} 端點測試"""

    async def test_get_card_rules_returns_only_card(self, api_client):
        """建立 card + stagelist 規則，GET /sync-rules/card 只返回 card 規則。"""
        await api_client.post("/api/v1/sync-rules", json={
            "entity_type": "card",
            "field_name": "title",
            "writable_by": "both",
        })
        await api_client.post("/api/v1/sync-rules", json={
            "entity_type": "stagelist",
            "field_name": "name",
            "writable_by": "human",
        })

        resp = await api_client.get("/api/v1/sync-rules/card")
        assert resp.status_code == 200
        rules = resp.json()
        assert len(rules) == 1
        assert rules[0]["entity_type"] == "card"
        assert rules[0]["field_name"] == "title"

    async def test_get_unknown_entity_returns_empty(self, api_client):
        """GET /sync-rules/nonexistent 返回空 list。"""
        resp = await api_client.get("/api/v1/sync-rules/nonexistent")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_get_stagelist_rules(self, api_client):
        """確認 stagelist 規則正確返回。"""
        await api_client.post("/api/v1/sync-rules", json={
            "entity_type": "stagelist",
            "field_name": "name",
            "writable_by": "human",
            "conflict_strategy": "human_wins",
        })
        await api_client.post("/api/v1/sync-rules", json={
            "entity_type": "stagelist",
            "field_name": "position",
            "writable_by": "human",
            "conflict_strategy": "human_wins",
        })

        resp = await api_client.get("/api/v1/sync-rules/stagelist")
        assert resp.status_code == 200
        rules = resp.json()
        assert len(rules) == 2
        field_names = {r["field_name"] for r in rules}
        assert field_names == {"name", "position"}
        assert all(r["entity_type"] == "stagelist" for r in rules)


class TestSyncRuleGetByIdAPI:
    """GET /sync-rules/{rule_id} 端點測試"""

    async def test_get_existing_rule_by_id(self, api_client):
        """成功取得單一規則。"""
        create_resp = await api_client.post("/api/v1/sync-rules", json={
            "entity_type": "card",
            "field_name": "title",
            "writable_by": "both",
            "conflict_strategy": "last_write_wins",
        })
        rule_id = create_resp.json()["id"]

        resp = await api_client.get(f"/api/v1/sync-rules/{rule_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == rule_id
        assert data["entity_type"] == "card"
        assert data["field_name"] == "title"
        assert data["writable_by"] == "both"
        assert data["conflict_strategy"] == "last_write_wins"
        assert data["is_enabled"] is True

    async def test_get_nonexistent_rule_returns_404(self, api_client):
        """不存在的 rule_id 應回傳 404。"""
        resp = await api_client.get("/api/v1/sync-rules/99999")
        assert resp.status_code == 404

    async def test_get_by_id_after_update(self, api_client):
        """更新後 GET by ID 回傳最新值。"""
        create_resp = await api_client.post("/api/v1/sync-rules", json={
            "entity_type": "card",
            "field_name": "description",
            "conflict_strategy": "human_wins",
        })
        rule_id = create_resp.json()["id"]

        await api_client.put(f"/api/v1/sync-rules/{rule_id}", json={
            "conflict_strategy": "ai_merge",
        })

        resp = await api_client.get(f"/api/v1/sync-rules/{rule_id}")
        assert resp.status_code == 200
        assert resp.json()["conflict_strategy"] == "ai_merge"

    async def test_get_by_entity_still_works(self, api_client):
        """確認 GET /sync-rules/{entity_type} 路由不受影響。"""
        await api_client.post("/api/v1/sync-rules", json={
            "entity_type": "card",
            "field_name": "status",
        })
        resp = await api_client.get("/api/v1/sync-rules/card")
        assert resp.status_code == 200
        rules = resp.json()
        assert isinstance(rules, list)
        assert len(rules) >= 1


# ==========================================================
# is_enabled 停用/啟用整合測試
# ==========================================================

class TestSyncRuleIsEnabledToggle:
    """is_enabled 停用/啟用整合測試 — 驗證停用規則後權限行為變更"""

    def test_disable_rule_allows_previously_blocked_write(self, db_session):
        """建立 human-only rule → AI 被攔截 → is_enabled=False → AI 可寫（fallback default）"""
        rule_status = SyncRuleModel(
            entity_type="card", field_name="status",
            writable_by="human", conflict_strategy="last_write_wins", is_enabled=True,
        )
        rule_title = SyncRuleModel(
            entity_type="card", field_name="title",
            writable_by="both", conflict_strategy="last_write_wins", is_enabled=True,
        )
        db_session.add(rule_status)
        db_session.add(rule_title)
        db_session.commit()

        registry = load_registry_from_db(db_session)
        enforcer = SyncEnforcer(registry)
        result_ai = enforcer.validate("card", {"status": "running"}, "ai")
        assert len(result_ai.rejected) == 1
        assert result_ai.rejected[0].field_name == "status"

        result_human = enforcer.validate("card", {"status": "running"}, "human")
        assert "status" in result_human.approved

        db_session.refresh(rule_status)
        rule_status.is_enabled = False
        db_session.add(rule_status)
        db_session.commit()

        registry2 = load_registry_from_db(db_session)
        enforcer2 = SyncEnforcer(registry2)
        result2 = enforcer2.validate("card", {"status": "running"}, "ai")
        assert "status" in result2.approved
        assert len(result2.rejected) == 0

    def test_reenable_rule_blocks_write(self, db_session):
        """停用 → 重新啟用 → AI 再次被攔截"""
        rule_status = SyncRuleModel(
            entity_type="card", field_name="status",
            writable_by="human", conflict_strategy="last_write_wins", is_enabled=True,
        )
        rule_title = SyncRuleModel(
            entity_type="card", field_name="title",
            writable_by="both", conflict_strategy="last_write_wins", is_enabled=True,
        )
        db_session.add(rule_status)
        db_session.add(rule_title)
        db_session.commit()

        db_session.refresh(rule_status)
        rule_status.is_enabled = False
        db_session.add(rule_status)
        db_session.commit()

        registry = load_registry_from_db(db_session)
        enforcer = SyncEnforcer(registry)
        result = enforcer.validate("card", {"status": "running"}, "ai")
        assert "status" in result.approved

        db_session.refresh(rule_status)
        rule_status.is_enabled = True
        db_session.add(rule_status)
        db_session.commit()

        registry2 = load_registry_from_db(db_session)
        enforcer2 = SyncEnforcer(registry2)
        result2 = enforcer2.validate("card", {"status": "running"}, "ai")
        assert "status" not in result2.approved
        assert len(result2.rejected) == 1
        assert result2.rejected[0].field_name == "status"


# ==========================================================
# Member SyncEnforcer 整合測試
# ==========================================================

def _make_member_registry() -> SyncRuleRegistry:
    """建立 member entity 的 SyncRuleRegistry（對齊 seed.py 預設規則）。"""
    registry = SyncRuleRegistry()
    field_rules = (
        FieldRule("name", SyncDirection.HUMAN_TO_AI, ConflictStrategy.HUMAN_WINS, frozenset({"human"})),
        FieldRule("role", SyncDirection.HUMAN_TO_AI, ConflictStrategy.HUMAN_WINS, frozenset({"human"})),
        FieldRule("avatar", SyncDirection.HUMAN_TO_AI, ConflictStrategy.HUMAN_WINS, frozenset({"human"})),
        FieldRule("description", SyncDirection.BIDIRECTIONAL, ConflictStrategy.LAST_WRITE_WINS, frozenset({"ai", "human"})),
        FieldRule("hook_profile", SyncDirection.HUMAN_TO_AI, ConflictStrategy.HUMAN_WINS, frozenset({"human"})),
    )
    registry.register(SyncRuleDomain(
        entity_type="member",
        field_rules=field_rules,
        default_direction=SyncDirection.BIDIRECTIONAL,
        default_strategy=ConflictStrategy.LAST_WRITE_WINS,
    ))
    return registry


class TestMemberSyncEnforcement:
    """Member entity 的 SyncEnforcer 整合測試。"""

    def test_ai_change_name_rejected(self):
        enforcer = SyncEnforcer(_make_member_registry())
        result = enforcer.validate("member", {"name": "AI-Name"}, "ai")
        assert len(result.approved) == 0
        assert len(result.rejected) == 1
        assert result.rejected[0].field_name == "name"

    def test_human_change_name_approved(self):
        enforcer = SyncEnforcer(_make_member_registry())
        result = enforcer.validate("member", {"name": "Human-Name"}, "human")
        assert result.approved == {"name": "Human-Name"}
        assert len(result.rejected) == 0

    def test_both_change_description_approved(self):
        enforcer = SyncEnforcer(_make_member_registry())

        result_human = enforcer.validate("member", {"description": "by human"}, "human")
        assert result_human.approved == {"description": "by human"}
        assert len(result_human.rejected) == 0

        result_ai = enforcer.validate("member", {"description": "by ai"}, "ai")
        assert result_ai.approved == {"description": "by ai"}
        assert len(result_ai.rejected) == 0

    def test_metadata_bypass(self):
        """sprite_index 等 metadata 欄位不在 SyncRule 中，走 default_direction (BIDIRECTIONAL)。"""
        enforcer = SyncEnforcer(_make_member_registry())
        result = enforcer.validate("member", {"sprite_index": 5}, "ai")
        assert result.approved == {"sprite_index": 5}
        assert len(result.rejected) == 0

    def test_ai_change_role_rejected(self):
        enforcer = SyncEnforcer(_make_member_registry())
        result = enforcer.validate("member", {"role": "admin"}, "ai")
        assert len(result.approved) == 0
        assert result.rejected[0].field_name == "role"

    def test_ai_change_hook_profile_rejected(self):
        enforcer = SyncEnforcer(_make_member_registry())
        result = enforcer.validate("member", {"hook_profile": "strict"}, "ai")
        assert len(result.approved) == 0
        assert result.rejected[0].field_name == "hook_profile"

    def test_mixed_fields_partial_approval(self):
        enforcer = SyncEnforcer(_make_member_registry())
        changes = {"name": "AI-Name", "description": "new desc", "avatar": "pic.png"}
        result = enforcer.validate("member", changes, "ai")
        assert "description" in result.approved
        assert "name" not in result.approved
        assert "avatar" not in result.approved
        assert len(result.rejected) == 2


# ==========================================================
# Project SyncEnforcer 整合測試
# ==========================================================

def _make_project_registry() -> SyncRuleRegistry:
    """建立 project entity 的 SyncRuleRegistry（對齊 seed.py 預設規則）。"""
    registry = SyncRuleRegistry()
    field_rules = (
        FieldRule("name", SyncDirection.HUMAN_TO_AI, ConflictStrategy.HUMAN_WINS, frozenset({"human"})),
        FieldRule("path", SyncDirection.HUMAN_TO_AI, ConflictStrategy.HUMAN_WINS, frozenset({"human"})),
        FieldRule("is_active", SyncDirection.HUMAN_TO_AI, ConflictStrategy.HUMAN_WINS, frozenset({"human"})),
        FieldRule("deploy_type", SyncDirection.HUMAN_TO_AI, ConflictStrategy.HUMAN_WINS, frozenset({"human"})),
    )
    registry.register(SyncRuleDomain(
        entity_type="project",
        field_rules=field_rules,
        default_direction=SyncDirection.BIDIRECTIONAL,
        default_strategy=ConflictStrategy.LAST_WRITE_WINS,
    ))
    return registry


class TestProjectSyncEnforcement:
    """Project entity 的 SyncEnforcer 整合測試。"""

    def test_ai_rejected_on_human_only_project_field(self):
        """actor=ai 修改 name 被拒（writable_by=human）"""
        enforcer = SyncEnforcer(_make_project_registry())
        result = enforcer.validate("project", {"name": "AI-Project"}, "ai")
        assert len(result.approved) == 0
        assert len(result.rejected) == 1
        assert result.rejected[0].field_name == "name"

    def test_human_can_update_project_name(self):
        """actor=human 修改 name 正常通過"""
        enforcer = SyncEnforcer(_make_project_registry())
        result = enforcer.validate("project", {"name": "Human-Project"}, "human")
        assert result.approved == {"name": "Human-Project"}
        assert len(result.rejected) == 0

    def test_metadata_bypass_sync_rules(self):
        """default_member_id 等 metadata 欄位不在 SyncRule 中，走 default_direction (BIDIRECTIONAL)。"""
        enforcer = SyncEnforcer(_make_project_registry())
        result = enforcer.validate("project", {"default_member_id": 42}, "ai")
        assert result.approved == {"default_member_id": 42}
        assert len(result.rejected) == 0

    def test_no_rules_rejects_all(self):
        """無任何 project rule 時，entity 未註冊，所有欄位被拒。"""
        registry = SyncRuleRegistry()
        enforcer = SyncEnforcer(registry)
        result = enforcer.validate("project", {"name": "Any", "path": "/tmp"}, "ai")
        assert len(result.approved) == 0
        assert len(result.rejected) == 2

    def test_ai_rejected_on_all_sync_fields(self):
        """actor=ai 同時修改多個 sync 欄位全部被拒"""
        enforcer = SyncEnforcer(_make_project_registry())
        changes = {"name": "AI", "path": "/ai", "is_active": False, "deploy_type": "cloud"}
        result = enforcer.validate("project", changes, "ai")
        assert len(result.approved) == 0
        assert len(result.rejected) == 4

    def test_human_approved_on_all_sync_fields(self):
        """actor=human 同時修改多個 sync 欄位全部通過"""
        enforcer = SyncEnforcer(_make_project_registry())
        changes = {"name": "Human", "path": "/human", "is_active": True, "deploy_type": "local"}
        result = enforcer.validate("project", changes, "human")
        assert len(result.approved) == 4
        assert len(result.rejected) == 0

    def test_mixed_sync_and_metadata(self):
        """AI 送 sync + metadata 欄位：sync 被拒、metadata 走 default 通過"""
        enforcer = SyncEnforcer(_make_project_registry())
        changes = {"name": "AI-Name", "deploy_type": "cloud", "default_member_id": 5, "room_id": 3}
        result = enforcer.validate("project", changes, "ai")
        assert "name" not in result.approved
        assert "deploy_type" not in result.approved
        assert result.approved["default_member_id"] == 5
        assert result.approved["room_id"] == 3
        assert len(result.rejected) == 2


# ==========================================================
# POST /cards/{card_id}/resolve-conflicts 端點測試
# ==========================================================

@pytest.fixture
async def conflict_client(tmp_path):
    """建立含 project/card 的 async httpx 測試客戶端（for resolve-conflicts 測試）。"""
    db_path = tmp_path / "test_conflict.db"
    engine = create_engine(f"sqlite:///{db_path}")
    SQLModel.metadata.create_all(engine)

    now = datetime(2026, 4, 10, 12, 0, 0, tzinfo=timezone.utc)
    project_path = tmp_path / "test-project"
    cards_dir = project_path / ".aegis" / "cards"
    cards_dir.mkdir(parents=True)

    with Session(engine) as session:
        project = Project(id=1, name="Test Project", path=str(project_path))
        session.add(project)
        backlog = StageList(id=1, project_id=1, name="Backlog", position=0, is_ai_stage=False)
        session.add(backlog)
        session.commit()

        card_data = CardData(
            id=1, list_id=1, title="Original Title",
            description="Original Desc", content="Original Content",
            status="idle", tags=[],
            created_at=now, updated_at=now,
        )
        fpath = card_file_path(str(project_path), 1)
        fpath.parent.mkdir(parents=True, exist_ok=True)
        write_card(fpath, card_data)
        sync_card_to_index(session, card_data, project_id=1, file_path=str(fpath))

        orm_card = Card(
            id=1, list_id=1, title="Original Title",
            description="Original Desc", status="idle",
            created_at=now, updated_at=now,
        )
        session.add(orm_card)
        session.commit()

    from app.main import app
    from app.database import get_session

    def _override():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = _override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield {
            "client": client,
            "engine": engine,
            "fpath": fpath,
            "now": now,
        }
    app.dependency_overrides.clear()


class TestResolveConflictsAPI:
    """POST /cards/{card_id}/resolve-conflicts 端點測試"""

    async def test_resolve_conflicts_lww_apply_true(self, conflict_client):
        """apply_resolved=True + last_write_wins：已解決欄位寫回卡片 MD 和 ORM"""
        client = conflict_client["client"]
        engine = conflict_client["engine"]
        fpath = conflict_client["fpath"]
        now = conflict_client["now"]

        with Session(engine) as s:
            s.add(SyncRuleModel(
                entity_type="card", field_name="title",
                writable_by="both", conflict_strategy="last_write_wins", is_enabled=True,
            ))
            s.commit()

        local_ts = (now + timedelta(hours=1)).isoformat()
        resp = await client.post("/api/v1/cards/1/resolve-conflicts", json={
            "local_changes": {
                "title": {"value": "Updated Title", "updated_at": local_ts, "actor": "human"},
            },
            "apply_resolved": True,
        })

        assert resp.status_code == 200
        data = resp.json()
        assert data["applied"] is True
        assert len(data["resolved"]) == 1
        assert data["resolved"][0]["field_name"] == "title"
        assert data["resolved"][0]["value"] == "Updated Title"
        assert data["resolved"][0]["strategy"] == "last_write_wins"
        assert len(data["deferred"]) == 0

        cd = read_card(fpath)
        assert cd.title == "Updated Title"

        with Session(engine) as s:
            orm_card = s.get(Card, 1)
            assert orm_card.title == "Updated Title"

    async def test_resolve_conflicts_lww_apply_false(self, conflict_client):
        """apply_resolved=False + last_write_wins：回傳解決方案但卡片內容不變"""
        client = conflict_client["client"]
        engine = conflict_client["engine"]
        fpath = conflict_client["fpath"]
        now = conflict_client["now"]

        with Session(engine) as s:
            s.add(SyncRuleModel(
                entity_type="card", field_name="title",
                writable_by="both", conflict_strategy="last_write_wins", is_enabled=True,
            ))
            s.commit()

        local_ts = (now + timedelta(hours=1)).isoformat()
        resp = await client.post("/api/v1/cards/1/resolve-conflicts", json={
            "local_changes": {
                "title": {"value": "Updated Title", "updated_at": local_ts, "actor": "human"},
            },
            "apply_resolved": False,
        })

        assert resp.status_code == 200
        data = resp.json()
        assert data["applied"] is False
        assert len(data["resolved"]) == 1
        assert data["resolved"][0]["value"] == "Updated Title"
        assert len(data["deferred"]) == 0

        cd = read_card(fpath)
        assert cd.title == "Original Title"

        with Session(engine) as s:
            orm_card = s.get(Card, 1)
            assert orm_card.title == "Original Title"

    async def test_resolve_conflicts_deferred_manual_merge(self, conflict_client):
        """manual_merge 策略：雙方都有變更時欄位進入 deferred 列表"""
        client = conflict_client["client"]
        now = conflict_client["now"]

        with Session(conflict_client["engine"]) as s:
            s.add(SyncRuleModel(
                entity_type="card", field_name="description",
                writable_by="both", conflict_strategy="manual_merge", is_enabled=True,
            ))
            s.commit()

        local_ts = (now + timedelta(hours=1)).isoformat()
        resp = await client.post("/api/v1/cards/1/resolve-conflicts", json={
            "local_changes": {
                "description": {"value": "Local Desc", "updated_at": local_ts, "actor": "ai"},
            },
            "apply_resolved": True,
        })

        assert resp.status_code == 200
        data = resp.json()
        assert data["applied"] is False
        assert len(data["resolved"]) == 0
        assert len(data["deferred"]) == 1
        assert data["deferred"][0]["field_name"] == "description"
        assert data["deferred"][0]["strategy"] == "manual_merge"
        assert data["deferred"][0]["local"]["value"] == "Local Desc"
        assert data["deferred"][0]["remote"]["value"] == "Original Desc"

    async def test_resolve_conflicts_card_not_found(self, conflict_client):
        """card_id 不存在時回傳 404"""
        client = conflict_client["client"]
        now = conflict_client["now"]

        resp = await client.post("/api/v1/cards/9999/resolve-conflicts", json={
            "local_changes": {
                "title": {"value": "X", "updated_at": now.isoformat(), "actor": "human"},
            },
        })
        assert resp.status_code == 404

    async def test_resolve_conflicts_human_wins(self, conflict_client):
        """human_wins 策略：local actor=ai 時 remote（human 端）版本勝出"""
        client = conflict_client["client"]
        engine = conflict_client["engine"]
        fpath = conflict_client["fpath"]
        now = conflict_client["now"]

        with Session(engine) as s:
            s.add(SyncRuleModel(
                entity_type="card", field_name="title",
                writable_by="both", conflict_strategy="human_wins", is_enabled=True,
            ))
            s.commit()

        local_ts = (now + timedelta(hours=1)).isoformat()
        resp = await client.post("/api/v1/cards/1/resolve-conflicts", json={
            "local_changes": {
                "title": {"value": "AI Title", "updated_at": local_ts, "actor": "ai"},
            },
            "apply_resolved": True,
        })

        assert resp.status_code == 200
        data = resp.json()
        assert data["applied"] is True
        assert len(data["resolved"]) == 1
        assert data["resolved"][0]["field_name"] == "title"
        assert data["resolved"][0]["value"] == "Original Title"
        assert data["resolved"][0]["strategy"] == "human_wins"

        cd = read_card(fpath)
        assert cd.title == "Original Title"


# ==========================================================
# CronJob SyncEnforcer 整合測試
# ==========================================================

def _make_cronjob_registry() -> SyncRuleRegistry:
    """建立 cronjob entity 的 SyncRuleRegistry（對齊 seed.py 預設規則）。"""
    registry = SyncRuleRegistry()
    field_rules = (
        FieldRule("cron_expression", SyncDirection.HUMAN_TO_AI, ConflictStrategy.HUMAN_WINS, frozenset({"human"})),
        FieldRule("is_enabled", SyncDirection.HUMAN_TO_AI, ConflictStrategy.HUMAN_WINS, frozenset({"human"})),
        FieldRule("name", SyncDirection.HUMAN_TO_AI, ConflictStrategy.HUMAN_WINS, frozenset({"human"})),
        FieldRule("system_instruction", SyncDirection.HUMAN_TO_AI, ConflictStrategy.HUMAN_WINS, frozenset({"human"})),
        FieldRule("prompt_template", SyncDirection.BIDIRECTIONAL, ConflictStrategy.LAST_WRITE_WINS, frozenset({"human", "ai"})),
        FieldRule("description", SyncDirection.BIDIRECTIONAL, ConflictStrategy.LAST_WRITE_WINS, frozenset({"human", "ai"})),
        FieldRule("target_list_id", SyncDirection.HUMAN_TO_AI, ConflictStrategy.HUMAN_WINS, frozenset({"human"})),
    )
    registry.register(SyncRuleDomain(
        entity_type="cronjob",
        field_rules=field_rules,
        default_direction=SyncDirection.BIDIRECTIONAL,
        default_strategy=ConflictStrategy.LAST_WRITE_WINS,
    ))
    return registry


class TestCronJobSyncEnforcement:
    """CronJob entity 的 SyncEnforcer 整合測試。"""

    def test_ai_change_cron_expression_rejected(self):
        """actor=ai 修改 cron_expression 被拒（writable_by=human）"""
        enforcer = SyncEnforcer(_make_cronjob_registry())
        result = enforcer.validate("cronjob", {"cron_expression": "*/5 * * * *"}, "ai")
        assert len(result.approved) == 0
        assert len(result.rejected) == 1
        assert result.rejected[0].field_name == "cron_expression"

    def test_human_change_cron_expression_approved(self):
        """actor=human 修改 cron_expression 正常通過"""
        enforcer = SyncEnforcer(_make_cronjob_registry())
        result = enforcer.validate("cronjob", {"cron_expression": "0 9 * * *"}, "human")
        assert result.approved == {"cron_expression": "0 9 * * *"}
        assert len(result.rejected) == 0

    def test_both_change_description_approved(self):
        """writable_by=both 的 description，AI 和 human 都能修改"""
        enforcer = SyncEnforcer(_make_cronjob_registry())
        result_ai = enforcer.validate("cronjob", {"description": "AI desc"}, "ai")
        assert result_ai.approved == {"description": "AI desc"}
        assert len(result_ai.rejected) == 0

        result_human = enforcer.validate("cronjob", {"description": "Human desc"}, "human")
        assert result_human.approved == {"description": "Human desc"}
        assert len(result_human.rejected) == 0

    def test_mixed_fields_partial_approval(self):
        """AI 同時修改 human-only 和 both 欄位：部分通過、部分拒絕"""
        enforcer = SyncEnforcer(_make_cronjob_registry())
        changes = {
            "cron_expression": "*/10 * * * *",
            "is_enabled": False,
            "name": "AI Job",
            "description": "AI 修改的描述",
            "prompt_template": "new prompt",
        }
        result = enforcer.validate("cronjob", changes, "ai")
        assert "description" in result.approved
        assert "prompt_template" in result.approved
        assert len(result.approved) == 2
        rejected_fields = {r.field_name for r in result.rejected}
        assert rejected_fields == {"cron_expression", "is_enabled", "name"}
        assert len(result.rejected) == 3


# ==========================================================
# Person SyncEnforcer 整合測試
# ==========================================================

def _make_person_registry() -> SyncRuleRegistry:
    """建立 person entity 的 SyncRuleRegistry（對齊 seed.py 預設規則）。"""
    registry = SyncRuleRegistry()
    field_rules = (
        FieldRule("display_name", SyncDirection.HUMAN_TO_AI, ConflictStrategy.HUMAN_WINS, frozenset({"human"})),
        FieldRule("description", SyncDirection.BIDIRECTIONAL, ConflictStrategy.LAST_WRITE_WINS, frozenset({"ai", "human"})),
        FieldRule("level", SyncDirection.HUMAN_TO_AI, ConflictStrategy.HUMAN_WINS, frozenset({"human"})),
        FieldRule("access_expires_at", SyncDirection.HUMAN_TO_AI, ConflictStrategy.HUMAN_WINS, frozenset({"human"})),
        FieldRule("is_active", SyncDirection.HUMAN_TO_AI, ConflictStrategy.HUMAN_WINS, frozenset({"human"})),
    )
    registry.register(SyncRuleDomain(
        entity_type="person",
        field_rules=field_rules,
        default_direction=SyncDirection.BIDIRECTIONAL,
        default_strategy=ConflictStrategy.LAST_WRITE_WINS,
    ))
    return registry


class TestPersonSyncEnforcement:
    """Person entity 的 SyncEnforcer 整合測試。"""

    def test_person_update_human_fields_by_ai_rejected(self):
        """AI actor 嘗試修改 human-only 欄位被拒絕"""
        enforcer = SyncEnforcer(_make_person_registry())
        changes = {"display_name": "AI-Name", "level": 3, "is_active": False}
        result = enforcer.validate("person", changes, "ai")
        assert len(result.approved) == 0
        assert len(result.rejected) == 3
        rejected_fields = {r.field_name for r in result.rejected}
        assert rejected_fields == {"display_name", "level", "is_active"}

    def test_person_update_both_fields_by_ai_accepted(self):
        """AI actor 修改 writable_by=both 的 description 被允許"""
        enforcer = SyncEnforcer(_make_person_registry())
        result = enforcer.validate("person", {"description": "AI desc"}, "ai")
        assert result.approved == {"description": "AI desc"}
        assert len(result.rejected) == 0

    def test_person_update_by_human_all_accepted(self):
        """Human actor 可修改所有欄位"""
        enforcer = SyncEnforcer(_make_person_registry())
        changes = {
            "display_name": "Human-Name",
            "description": "human desc",
            "level": 2,
            "access_expires_at": "2026-12-31T00:00:00Z",
            "is_active": True,
        }
        result = enforcer.validate("person", changes, "human")
        assert result.approved == changes
        assert len(result.rejected) == 0

    def test_person_ai_change_access_expires_at_rejected(self):
        """AI actor 不能修改 access_expires_at"""
        enforcer = SyncEnforcer(_make_person_registry())
        result = enforcer.validate("person", {"access_expires_at": "2026-01-01"}, "ai")
        assert len(result.approved) == 0
        assert result.rejected[0].field_name == "access_expires_at"

    def test_person_mixed_fields_partial_approval(self):
        """AI 同時修改 human-only 和 both 欄位：部分通過、部分拒絕"""
        enforcer = SyncEnforcer(_make_person_registry())
        changes = {"display_name": "AI-Name", "description": "new desc", "level": 5}
        result = enforcer.validate("person", changes, "ai")
        assert "description" in result.approved
        assert len(result.approved) == 1
        rejected_fields = {r.field_name for r in result.rejected}
        assert rejected_fields == {"display_name", "level"}
        assert len(result.rejected) == 2


# ==========================================================
# Actor 參數驗證測試
# ==========================================================

class TestActorValidation:
    """驗證 actor query param 不合法時回 400"""

    async def test_patch_card_invalid_actor_returns_400(self, conflict_client):
        """PATCH /cards/{card_id}?actor=robot → 400"""
        client = conflict_client["client"]
        resp = await client.patch(
            "/api/v1/cards/1",
            json={"title": "New Title"},
            params={"actor": "robot"},
        )
        assert resp.status_code == 400
        assert "Invalid actor" in resp.json()["detail"]

    async def test_patch_card_valid_actor_ai_accepted(self, conflict_client):
        """PATCH /cards/{card_id}?actor=ai → 不回 400（actor 合法）"""
        client = conflict_client["client"]
        resp = await client.patch(
            "/api/v1/cards/1",
            json={"title": "AI Title"},
            params={"actor": "ai"},
        )
        assert resp.status_code != 400

    async def test_resolve_conflicts_invalid_remote_actor_returns_400(self, conflict_client):
        """remote_actor="bot" → 400"""
        client = conflict_client["client"]
        now = conflict_client["now"]
        resp = await client.post("/api/v1/cards/1/resolve-conflicts", json={
            "local_changes": {
                "title": {"value": "X", "updated_at": now.isoformat(), "actor": "human"},
            },
            "remote_actor": "bot",
        })
        assert resp.status_code == 400
        assert "Invalid actor" in resp.json()["detail"]


# ==========================================================
# remote_actor 欄位功能測試
# ==========================================================

class TestRemoteActorField:
    """驗證 resolve-conflicts 使用 remote_actor 欄位判斷遠端版本的 actor 身份"""

    async def test_ai_wins_with_remote_actor_ai(self, conflict_client):
        """ai_wins 策略 + remote_actor=ai → remote 版本勝出"""
        client = conflict_client["client"]
        engine = conflict_client["engine"]
        fpath = conflict_client["fpath"]
        now = conflict_client["now"]

        with Session(engine) as s:
            s.add(SyncRuleModel(
                entity_type="card", field_name="title",
                writable_by="both", conflict_strategy="ai_wins", is_enabled=True,
            ))
            s.commit()

        local_ts = (now + timedelta(hours=1)).isoformat()
        resp = await client.post("/api/v1/cards/1/resolve-conflicts", json={
            "local_changes": {
                "title": {"value": "Human Title", "updated_at": local_ts, "actor": "human"},
            },
            "apply_resolved": True,
            "remote_actor": "ai",
        })

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["resolved"]) == 1
        assert data["resolved"][0]["strategy"] == "ai_wins"
        assert data["resolved"][0]["value"] == "Original Title"

    async def test_human_wins_with_remote_actor_human(self, conflict_client):
        """human_wins 策略 + remote_actor=human（預設值） → remote 版本勝出"""
        client = conflict_client["client"]
        engine = conflict_client["engine"]
        now = conflict_client["now"]

        with Session(engine) as s:
            s.add(SyncRuleModel(
                entity_type="card", field_name="title",
                writable_by="both", conflict_strategy="human_wins", is_enabled=True,
            ))
            s.commit()

        local_ts = (now + timedelta(hours=1)).isoformat()
        resp = await client.post("/api/v1/cards/1/resolve-conflicts", json={
            "local_changes": {
                "title": {"value": "AI Title", "updated_at": local_ts, "actor": "ai"},
            },
            "apply_resolved": False,
        })

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["resolved"]) == 1
        assert data["resolved"][0]["strategy"] == "human_wins"
        assert data["resolved"][0]["value"] == "Original Title"


# ==========================================================
# PendingConflict 持久化測試
# ==========================================================

class TestPendingConflictPersistence:
    """deferred 衝突持久化到 PendingConflict 表的整合測試"""

    async def test_deferred_conflict_persisted(self, conflict_client):
        """manual_merge 觸發後，DB 中應有 PendingConflict 記錄"""
        client = conflict_client["client"]
        engine = conflict_client["engine"]
        now = conflict_client["now"]

        with Session(engine) as s:
            s.add(SyncRuleModel(
                entity_type="card", field_name="description",
                writable_by="both", conflict_strategy="manual_merge", is_enabled=True,
            ))
            s.commit()

        local_ts = (now + timedelta(hours=1)).isoformat()
        resp = await client.post("/api/v1/cards/1/resolve-conflicts", json={
            "local_changes": {
                "description": {"value": "Local Desc", "updated_at": local_ts, "actor": "ai"},
            },
            "apply_resolved": False,
        })

        assert resp.status_code == 200
        assert len(resp.json()["deferred"]) == 1

        from app.models.core import PendingConflict
        with Session(engine) as s:
            conflicts = s.exec(
                select(PendingConflict).where(
                    PendingConflict.card_id == 1,
                    PendingConflict.status == "pending",
                )
            ).all()
            assert len(conflicts) == 1
            pc = conflicts[0]
            assert pc.field_name == "description"
            assert pc.local_value == "Local Desc"
            assert pc.local_actor == "ai"
            assert pc.remote_value == "Original Desc"
            assert pc.remote_actor == "human"
            assert pc.strategy == "manual_merge"

    async def test_get_pending_conflicts(self, conflict_client):
        """GET /cards/{card_id}/pending-conflicts 回傳正確的待處理衝突"""
        client = conflict_client["client"]
        engine = conflict_client["engine"]
        now = conflict_client["now"]

        with Session(engine) as s:
            s.add(SyncRuleModel(
                entity_type="card", field_name="description",
                writable_by="both", conflict_strategy="manual_merge", is_enabled=True,
            ))
            s.commit()

        local_ts = (now + timedelta(hours=1)).isoformat()
        await client.post("/api/v1/cards/1/resolve-conflicts", json={
            "local_changes": {
                "description": {"value": "Local Desc", "updated_at": local_ts, "actor": "ai"},
            },
        })

        resp = await client.get("/api/v1/cards/1/pending-conflicts")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["field_name"] == "description"
        assert data[0]["status"] == "pending"
        assert data[0]["local_value"] == "Local Desc"
        assert data[0]["remote_value"] == "Original Desc"

        resp_filtered = await client.get("/api/v1/cards/1/pending-conflicts", params={"status": "resolved"})
        assert resp_filtered.status_code == 200
        assert len(resp_filtered.json()) == 0

    async def test_duplicate_pending_conflict_updates(self, conflict_client):
        """同一 card_id+field_name 重複觸發 deferred 時，更新而非建立多筆"""
        client = conflict_client["client"]
        engine = conflict_client["engine"]
        now = conflict_client["now"]

        with Session(engine) as s:
            s.add(SyncRuleModel(
                entity_type="card", field_name="description",
                writable_by="both", conflict_strategy="manual_merge", is_enabled=True,
            ))
            s.commit()

        local_ts_1 = (now + timedelta(hours=1)).isoformat()
        await client.post("/api/v1/cards/1/resolve-conflicts", json={
            "local_changes": {
                "description": {"value": "V1", "updated_at": local_ts_1, "actor": "ai"},
            },
        })

        local_ts_2 = (now + timedelta(hours=2)).isoformat()
        await client.post("/api/v1/cards/1/resolve-conflicts", json={
            "local_changes": {
                "description": {"value": "V2", "updated_at": local_ts_2, "actor": "ai"},
            },
        })

        from app.models.core import PendingConflict
        with Session(engine) as s:
            conflicts = s.exec(
                select(PendingConflict).where(
                    PendingConflict.card_id == 1,
                    PendingConflict.status == "pending",
                )
            ).all()
            assert len(conflicts) == 1
            assert conflicts[0].local_value == "V2"


# ==========================================================
# PATCH /cards/{card_id}/pending-conflicts/{conflict_id} 端點測試
# ==========================================================

class TestResolvePendingConflictAPI:
    """PATCH /cards/{card_id}/pending-conflicts/{conflict_id} 端點測試"""

    async def _create_pending_conflict(self, client, now):
        """輔助：建立一筆 pending 衝突並回傳 conflict_id"""
        local_ts = (now + timedelta(hours=1)).isoformat()
        await client.post("/api/v1/cards/1/resolve-conflicts", json={
            "local_changes": {
                "description": {"value": "Local Desc", "updated_at": local_ts, "actor": "ai"},
            },
        })
        resp = await client.get("/api/v1/cards/1/pending-conflicts", params={"status": "pending"})
        data = resp.json()
        assert len(data) >= 1
        return data[0]["id"]

    async def test_resolve_pending_conflict_happy_path(self, conflict_client):
        """resolved 時寫回 card MD + ORM Card（dual-write）"""
        client = conflict_client["client"]
        engine = conflict_client["engine"]
        fpath = conflict_client["fpath"]
        now = conflict_client["now"]

        with Session(engine) as s:
            s.add(SyncRuleModel(
                entity_type="card", field_name="description",
                writable_by="both", conflict_strategy="manual_merge", is_enabled=True,
            ))
            s.commit()

        conflict_id = await self._create_pending_conflict(client, now)

        resp = await client.patch(f"/api/v1/cards/1/pending-conflicts/{conflict_id}", json={
            "resolved_value": "Merged Desc",
            "status": "resolved",
        })

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "resolved"
        assert data["resolved_value"] == "Merged Desc"
        assert data["resolved_at"] is not None

        cd = read_card(fpath)
        assert cd.description == "Merged Desc"

        with Session(engine) as s:
            orm_card = s.get(Card, 1)
            assert orm_card.description == "Merged Desc"

    async def test_dismiss_pending_conflict(self, conflict_client):
        """dismissed 時不寫回卡片，狀態正確更新"""
        client = conflict_client["client"]
        engine = conflict_client["engine"]
        fpath = conflict_client["fpath"]
        now = conflict_client["now"]

        with Session(engine) as s:
            s.add(SyncRuleModel(
                entity_type="card", field_name="description",
                writable_by="both", conflict_strategy="manual_merge", is_enabled=True,
            ))
            s.commit()

        conflict_id = await self._create_pending_conflict(client, now)

        resp = await client.patch(f"/api/v1/cards/1/pending-conflicts/{conflict_id}", json={
            "status": "dismissed",
        })

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "dismissed"
        assert data["resolved_value"] is None

        cd = read_card(fpath)
        assert cd.description == "Original Desc"

        with Session(engine) as s:
            orm_card = s.get(Card, 1)
            assert orm_card.description == "Original Desc"

    async def test_resolve_already_resolved_returns_409(self, conflict_client):
        """已解決的衝突再次 resolve 應回傳 409"""
        client = conflict_client["client"]
        engine = conflict_client["engine"]
        now = conflict_client["now"]

        with Session(engine) as s:
            s.add(SyncRuleModel(
                entity_type="card", field_name="description",
                writable_by="both", conflict_strategy="manual_merge", is_enabled=True,
            ))
            s.commit()

        conflict_id = await self._create_pending_conflict(client, now)

        await client.patch(f"/api/v1/cards/1/pending-conflicts/{conflict_id}", json={
            "resolved_value": "Merged",
            "status": "resolved",
        })

        resp = await client.patch(f"/api/v1/cards/1/pending-conflicts/{conflict_id}", json={
            "resolved_value": "Again",
            "status": "resolved",
        })
        assert resp.status_code == 409

    async def test_resolve_not_found_returns_404(self, conflict_client):
        """不存在的 conflict_id 應回傳 404"""
        client = conflict_client["client"]

        resp = await client.patch("/api/v1/cards/1/pending-conflicts/99999", json={
            "resolved_value": "X",
            "status": "resolved",
        })
        assert resp.status_code == 404

    async def test_resolve_ai_merge_calls_ai(self, conflict_client, monkeypatch):
        """ai_merge 策略且 resolved_value=None 時呼叫 AI 合併"""
        client = conflict_client["client"]
        engine = conflict_client["engine"]
        now = conflict_client["now"]

        async def fake_run_ai_task(**kwargs):
            return {"output": "AI-merged description"}

        monkeypatch.setattr("app.api.cards.run_ai_task", fake_run_ai_task)

        with Session(engine) as s:
            s.add(SyncRuleModel(
                entity_type="card", field_name="description",
                writable_by="both", conflict_strategy="ai_merge", is_enabled=True,
            ))
            s.commit()

        local_ts = (now + timedelta(hours=1)).isoformat()
        await client.post("/api/v1/cards/1/resolve-conflicts", json={
            "local_changes": {
                "description": {"value": "Local Desc", "updated_at": local_ts, "actor": "ai"},
            },
        })
        resp = await client.get("/api/v1/cards/1/pending-conflicts", params={"status": "pending"})
        conflict_id = resp.json()[0]["id"]

        resp = await client.patch(f"/api/v1/cards/1/pending-conflicts/{conflict_id}", json={
            "status": "resolved",
        })

        assert resp.status_code == 200
        data = resp.json()
        assert data["resolved_value"] == "AI-merged description"

        with Session(engine) as s:
            orm_card = s.get(Card, 1)
            assert orm_card.description == "AI-merged description"

    async def test_resolve_is_archived_field(self, conflict_client):
        """動態欄位集能正確寫回 is_archived"""
        client = conflict_client["client"]
        engine = conflict_client["engine"]
        now = conflict_client["now"]

        with Session(engine) as s:
            s.add(SyncRuleModel(
                entity_type="card", field_name="is_archived",
                writable_by="both", conflict_strategy="manual_merge", is_enabled=True,
            ))
            s.commit()

        local_ts = (now + timedelta(hours=1)).isoformat()
        await client.post("/api/v1/cards/1/resolve-conflicts", json={
            "local_changes": {
                "is_archived": {"value": "True", "updated_at": local_ts, "actor": "human"},
            },
        })
        resp = await client.get("/api/v1/cards/1/pending-conflicts", params={"status": "pending"})
        conflict_id = resp.json()[0]["id"]

        resp = await client.patch(f"/api/v1/cards/1/pending-conflicts/{conflict_id}", json={
            "resolved_value": "True",
            "status": "resolved",
        })

        assert resp.status_code == 200

        with Session(engine) as s:
            orm_card = s.get(Card, 1)
            assert str(orm_card.is_archived) == "True"


class TestAiMergeResolution:
    """AI merge 策略端到端測試：驗證 run_ai_task 被正確呼叫並寫回結果"""

    async def test_ai_merge_passes_correct_prompt(self, conflict_client, monkeypatch):
        """驗證 AI merge 傳入正確的 field_name、local_value、remote_value"""
        client = conflict_client["client"]
        engine = conflict_client["engine"]
        now = conflict_client["now"]

        captured_kwargs = {}

        async def capture_run_ai_task(**kwargs):
            captured_kwargs.update(kwargs)
            return {"output": "Merged result"}

        monkeypatch.setattr("app.api.cards.run_ai_task", capture_run_ai_task)

        with Session(engine) as s:
            s.add(SyncRuleModel(
                entity_type="card", field_name="description",
                writable_by="both", conflict_strategy="ai_merge", is_enabled=True,
            ))
            s.commit()

        local_ts = (now + timedelta(hours=1)).isoformat()
        await client.post("/api/v1/cards/1/resolve-conflicts", json={
            "local_changes": {
                "description": {"value": "Local Desc", "updated_at": local_ts, "actor": "ai"},
            },
        })
        resp = await client.get("/api/v1/cards/1/pending-conflicts", params={"status": "pending"})
        conflict_id = resp.json()[0]["id"]

        await client.patch(f"/api/v1/cards/1/pending-conflicts/{conflict_id}", json={
            "status": "resolved",
        })

        assert captured_kwargs["phase"] == "CHAT"
        assert captured_kwargs["forced_provider"] == "gemini"
        assert captured_kwargs["model_override"] == "gemini-flash"
        assert "description" in captured_kwargs["prompt"]
        assert "Local Desc" in captured_kwargs["prompt"]
        assert "Original Desc" in captured_kwargs["prompt"]

    async def test_ai_merge_fallback_on_failure(self, conflict_client, monkeypatch):
        """AI 呼叫失敗時 fallback 到 local_value"""
        client = conflict_client["client"]
        engine = conflict_client["engine"]
        now = conflict_client["now"]

        async def failing_run_ai_task(**kwargs):
            raise RuntimeError("AI service unavailable")

        monkeypatch.setattr("app.api.cards.run_ai_task", failing_run_ai_task)

        with Session(engine) as s:
            s.add(SyncRuleModel(
                entity_type="card", field_name="description",
                writable_by="both", conflict_strategy="ai_merge", is_enabled=True,
            ))
            s.commit()

        local_ts = (now + timedelta(hours=1)).isoformat()
        await client.post("/api/v1/cards/1/resolve-conflicts", json={
            "local_changes": {
                "description": {"value": "Local Desc", "updated_at": local_ts, "actor": "ai"},
            },
        })
        resp = await client.get("/api/v1/cards/1/pending-conflicts", params={"status": "pending"})
        conflict_id = resp.json()[0]["id"]
        pc_data = resp.json()[0]

        resp = await client.patch(f"/api/v1/cards/1/pending-conflicts/{conflict_id}", json={
            "status": "resolved",
        })

        assert resp.status_code == 200
        data = resp.json()
        assert data["resolved_value"] == pc_data["local_value"]

    async def test_ai_merge_empty_output_fallback(self, conflict_client, monkeypatch):
        """AI 回傳空字串時 fallback 到 local_value"""
        client = conflict_client["client"]
        engine = conflict_client["engine"]
        now = conflict_client["now"]

        async def empty_run_ai_task(**kwargs):
            return {"output": ""}

        monkeypatch.setattr("app.api.cards.run_ai_task", empty_run_ai_task)

        with Session(engine) as s:
            s.add(SyncRuleModel(
                entity_type="card", field_name="description",
                writable_by="both", conflict_strategy="ai_merge", is_enabled=True,
            ))
            s.commit()

        local_ts = (now + timedelta(hours=1)).isoformat()
        await client.post("/api/v1/cards/1/resolve-conflicts", json={
            "local_changes": {
                "description": {"value": "Local Desc", "updated_at": local_ts, "actor": "ai"},
            },
        })
        resp = await client.get("/api/v1/cards/1/pending-conflicts", params={"status": "pending"})
        conflict_id = resp.json()[0]["id"]
        pc_data = resp.json()[0]

        resp = await client.patch(f"/api/v1/cards/1/pending-conflicts/{conflict_id}", json={
            "status": "resolved",
        })

        assert resp.status_code == 200
        data = resp.json()
        assert data["resolved_value"] == pc_data["local_value"]

    async def test_ai_merge_with_explicit_value_skips_ai(self, conflict_client, monkeypatch):
        """使用者提供 resolved_value 時不呼叫 AI"""
        client = conflict_client["client"]
        engine = conflict_client["engine"]
        now = conflict_client["now"]

        called = False

        async def should_not_be_called(**kwargs):
            nonlocal called
            called = True
            return {"output": "Should not appear"}

        monkeypatch.setattr("app.api.cards.run_ai_task", should_not_be_called)

        with Session(engine) as s:
            s.add(SyncRuleModel(
                entity_type="card", field_name="description",
                writable_by="both", conflict_strategy="ai_merge", is_enabled=True,
            ))
            s.commit()

        local_ts = (now + timedelta(hours=1)).isoformat()
        await client.post("/api/v1/cards/1/resolve-conflicts", json={
            "local_changes": {
                "description": {"value": "Local Desc", "updated_at": local_ts, "actor": "ai"},
            },
        })
        resp = await client.get("/api/v1/cards/1/pending-conflicts", params={"status": "pending"})
        conflict_id = resp.json()[0]["id"]

        resp = await client.patch(f"/api/v1/cards/1/pending-conflicts/{conflict_id}", json={
            "resolved_value": "Manual merge",
            "status": "resolved",
        })

        assert resp.status_code == 200
        assert resp.json()["resolved_value"] == "Manual merge"
        assert not called
