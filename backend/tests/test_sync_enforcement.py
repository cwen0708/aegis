"""SyncEnforcer 整合測試 — DB 規則載入 + Card PATCH 欄位級權限控制"""
import pytest
import httpx
from datetime import datetime, timezone
from pathlib import Path
from sqlmodel import Session, SQLModel, create_engine

from app.models.core import Project, Card, StageList, CardIndex
from app.models.core import SyncRule as SyncRuleModel
from app.core.card_file import CardData, write_card, read_card, card_file_path
from app.core.card_index import sync_card_to_index
from app.core.sync_matrix import (
    SyncEnforcer,
    ConflictResolver,
    FieldVersion,
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
