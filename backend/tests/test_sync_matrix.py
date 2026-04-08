"""Tests for Sync Matrix Engine."""
import pytest

from datetime import datetime

from app.core.sync_matrix import (
    ConflictResolver,
    ConflictResult,
    ConflictStrategy,
    DeferredField,
    FieldRule,
    FieldVersion,
    RejectedField,
    ResolvedField,
    SyncDirection,
    SyncEnforcer,
    SyncRule,
    SyncRuleRegistry,
    ValidatedChanges,
)


# ---------------------------------------------------------------------------
# FieldRule
# ---------------------------------------------------------------------------

class TestFieldRule:
    def test_creation(self):
        rule = FieldRule(
            field_name="description",
            sync_direction=SyncDirection.BIDIRECTIONAL,
            conflict_strategy=ConflictStrategy.MANUAL_MERGE,
            writable_by=frozenset({"ai", "human"}),
        )
        assert rule.field_name == "description"
        assert rule.sync_direction == SyncDirection.BIDIRECTIONAL
        assert rule.conflict_strategy == ConflictStrategy.MANUAL_MERGE
        assert rule.writable_by == frozenset({"ai", "human"})

    def test_frozen_immutability(self):
        rule = FieldRule(
            field_name="title",
            sync_direction=SyncDirection.AI_TO_HUMAN,
            conflict_strategy=ConflictStrategy.LAST_WRITE_WINS,
            writable_by=frozenset({"ai"}),
        )
        with pytest.raises(AttributeError):
            rule.field_name = "other"


# ---------------------------------------------------------------------------
# SyncRule
# ---------------------------------------------------------------------------

class TestSyncRule:
    def test_frozen_immutability(self):
        rule = SyncRule(
            entity_type="card",
            field_rules=(),
            default_direction=SyncDirection.BIDIRECTIONAL,
            default_strategy=ConflictStrategy.LAST_WRITE_WINS,
        )
        with pytest.raises(AttributeError):
            rule.entity_type = "other"

    def test_creation_with_field_rules(self):
        fr = FieldRule(
            field_name="title",
            sync_direction=SyncDirection.AI_TO_HUMAN,
            conflict_strategy=ConflictStrategy.LAST_WRITE_WINS,
            writable_by=frozenset({"ai"}),
        )
        rule = SyncRule(
            entity_type="card",
            field_rules=(fr,),
            default_direction=SyncDirection.BIDIRECTIONAL,
            default_strategy=ConflictStrategy.MANUAL_MERGE,
        )
        assert rule.entity_type == "card"
        assert len(rule.field_rules) == 1
        assert rule.field_rules[0].field_name == "title"


# ---------------------------------------------------------------------------
# SyncRuleRegistry
# ---------------------------------------------------------------------------

class TestSyncRuleRegistry:
    @staticmethod
    def _make_registry() -> SyncRuleRegistry:
        registry = SyncRuleRegistry()
        fr_title = FieldRule(
            "title", SyncDirection.AI_TO_HUMAN,
            ConflictStrategy.LAST_WRITE_WINS, frozenset({"ai"}),
        )
        fr_notes = FieldRule(
            "notes", SyncDirection.BIDIRECTIONAL,
            ConflictStrategy.MANUAL_MERGE, frozenset({"ai", "human"}),
        )
        rule = SyncRule(
            "card", (fr_title, fr_notes),
            SyncDirection.HUMAN_TO_AI, ConflictStrategy.LAST_WRITE_WINS,
        )
        registry.register(rule)
        return registry

    def test_register_and_get(self):
        registry = self._make_registry()
        rule = registry.get_rule("card")
        assert rule is not None
        assert rule.entity_type == "card"

    def test_get_nonexistent(self):
        registry = SyncRuleRegistry()
        assert registry.get_rule("unknown") is None

    def test_list_rules(self):
        registry = self._make_registry()
        rules = registry.list_rules()
        assert len(rules) == 1
        assert rules[0].entity_type == "card"

    # -- field-level access control --

    def test_check_writable_explicit_ai_only(self):
        registry = self._make_registry()
        assert registry.check_field_writable("card", "title", "ai") is True
        assert registry.check_field_writable("card", "title", "human") is False

    def test_check_writable_explicit_bidirectional(self):
        registry = self._make_registry()
        assert registry.check_field_writable("card", "notes", "ai") is True
        assert registry.check_field_writable("card", "notes", "human") is True

    # -- default fallback --

    def test_fallback_to_default_direction(self):
        registry = self._make_registry()
        # default_direction = HUMAN_TO_AI -> human can write, ai cannot
        assert registry.check_field_writable("card", "unknown_field", "human") is True
        assert registry.check_field_writable("card", "unknown_field", "ai") is False

    def test_fallback_read_only(self):
        registry = SyncRuleRegistry()
        rule = SyncRule("locked", (), SyncDirection.READ_ONLY, ConflictStrategy.LAST_WRITE_WINS)
        registry.register(rule)
        assert registry.check_field_writable("locked", "any", "ai") is False
        assert registry.check_field_writable("locked", "any", "human") is False

    def test_fallback_bidirectional(self):
        registry = SyncRuleRegistry()
        rule = SyncRule("open", (), SyncDirection.BIDIRECTIONAL, ConflictStrategy.AI_MERGE)
        registry.register(rule)
        assert registry.check_field_writable("open", "any", "ai") is True
        assert registry.check_field_writable("open", "any", "human") is True

    def test_unknown_entity_returns_false(self):
        registry = self._make_registry()
        assert registry.check_field_writable("unknown", "title", "ai") is False

    def test_register_overwrites(self):
        registry = SyncRuleRegistry()
        v1 = SyncRule("card", (), SyncDirection.READ_ONLY, ConflictStrategy.LAST_WRITE_WINS)
        v2 = SyncRule("card", (), SyncDirection.BIDIRECTIONAL, ConflictStrategy.AI_MERGE)
        registry.register(v1)
        registry.register(v2)
        result = registry.get_rule("card")
        assert result is not None
        assert result.default_direction == SyncDirection.BIDIRECTIONAL


# ---------------------------------------------------------------------------
# RejectedField / ValidatedChanges (frozen dataclass)
# ---------------------------------------------------------------------------

class TestRejectedField:
    def test_creation(self):
        rf = RejectedField(field_name="title", reason="not allowed")
        assert rf.field_name == "title"
        assert rf.reason == "not allowed"

    def test_frozen_immutability(self):
        rf = RejectedField(field_name="title", reason="no")
        with pytest.raises(AttributeError):
            rf.field_name = "other"


class TestValidatedChanges:
    def test_creation(self):
        vc = ValidatedChanges(
            approved={"title": "new"},
            rejected=(RejectedField("notes", "denied"),),
        )
        assert vc.approved == {"title": "new"}
        assert len(vc.rejected) == 1

    def test_frozen_immutability(self):
        vc = ValidatedChanges()
        with pytest.raises(AttributeError):
            vc.approved = {}

    def test_defaults(self):
        vc = ValidatedChanges()
        assert vc.approved == {}
        assert vc.rejected == ()


# ---------------------------------------------------------------------------
# SyncEnforcer
# ---------------------------------------------------------------------------

class TestSyncEnforcer:
    @staticmethod
    def _make_enforcer() -> SyncEnforcer:
        """card 實體：title=ai-only, notes=bidirectional, default=HUMAN_TO_AI"""
        registry = SyncRuleRegistry()
        fr_title = FieldRule(
            "title", SyncDirection.AI_TO_HUMAN,
            ConflictStrategy.LAST_WRITE_WINS, frozenset({"ai"}),
        )
        fr_notes = FieldRule(
            "notes", SyncDirection.BIDIRECTIONAL,
            ConflictStrategy.MANUAL_MERGE, frozenset({"ai", "human"}),
        )
        rule = SyncRule(
            "card", (fr_title, fr_notes),
            SyncDirection.HUMAN_TO_AI, ConflictStrategy.LAST_WRITE_WINS,
        )
        registry.register(rule)
        return SyncEnforcer(registry)

    # -- validate: 全部通過 --
    def test_validate_all_approved(self):
        enforcer = self._make_enforcer()
        result = enforcer.validate("card", {"title": "new", "notes": "note"}, "ai")
        assert len(result.approved) == 2
        assert result.approved["title"] == "new"
        assert result.approved["notes"] == "note"
        assert len(result.rejected) == 0

    # -- validate: 全部拒絕 --
    def test_validate_all_rejected(self):
        enforcer = self._make_enforcer()
        result = enforcer.validate("card", {"title": "new"}, "human")
        assert len(result.approved) == 0
        assert len(result.rejected) == 1
        assert result.rejected[0].field_name == "title"
        assert "human" in result.rejected[0].reason

    # -- validate: 部分通過 --
    def test_validate_partial(self):
        enforcer = self._make_enforcer()
        result = enforcer.validate("card", {"title": "new", "notes": "note"}, "human")
        assert "notes" in result.approved
        assert "title" not in result.approved
        assert len(result.rejected) == 1
        assert result.rejected[0].field_name == "title"

    # -- enforce: 只保留允許的欄位 --
    def test_enforce_returns_only_approved(self):
        enforcer = self._make_enforcer()
        result = enforcer.enforce("card", {"title": "new", "notes": "note"}, "human")
        assert result == {"notes": "note"}
        assert "title" not in result

    # -- enforce: 不修改傳入的 changes dict --
    def test_enforce_does_not_mutate_input(self):
        enforcer = self._make_enforcer()
        original = {"title": "new", "notes": "note"}
        enforcer.enforce("card", original, "human")
        assert original == {"title": "new", "notes": "note"}

    # -- entity_type 不存在 --
    def test_validate_unknown_entity_rejects_all(self):
        enforcer = self._make_enforcer()
        result = enforcer.validate("unknown", {"field": "val"}, "ai")
        assert len(result.approved) == 0
        assert len(result.rejected) == 1
        assert result.rejected[0].field_name == "field"

    def test_enforce_unknown_entity_returns_empty(self):
        enforcer = self._make_enforcer()
        result = enforcer.enforce("unknown", {"field": "val"}, "ai")
        assert result == {}

    # -- 空 changes dict --
    def test_validate_empty_changes(self):
        enforcer = self._make_enforcer()
        result = enforcer.validate("card", {}, "ai")
        assert result.approved == {}
        assert result.rejected == ()

    def test_enforce_empty_changes(self):
        enforcer = self._make_enforcer()
        result = enforcer.enforce("card", {}, "ai")
        assert result == {}


# ---------------------------------------------------------------------------
# FieldVersion / ResolvedField / DeferredField / ConflictResult (frozen)
# ---------------------------------------------------------------------------

class TestFieldVersion:
    def test_creation(self):
        fv = FieldVersion(value="hello", updated_at=datetime(2026, 1, 1), actor="ai")
        assert fv.value == "hello"
        assert fv.actor == "ai"

    def test_frozen_immutability(self):
        fv = FieldVersion(value="x", updated_at=datetime(2026, 1, 1), actor="ai")
        with pytest.raises(AttributeError):
            fv.value = "y"


class TestResolvedField:
    def test_creation(self):
        rf = ResolvedField("title", "val", ConflictStrategy.LAST_WRITE_WINS)
        assert rf.field_name == "title"
        assert rf.value == "val"
        assert rf.strategy == ConflictStrategy.LAST_WRITE_WINS

    def test_frozen_immutability(self):
        rf = ResolvedField("title", "val", ConflictStrategy.LAST_WRITE_WINS)
        with pytest.raises(AttributeError):
            rf.field_name = "other"


class TestDeferredField:
    def test_creation(self):
        local = FieldVersion("a", datetime(2026, 1, 1), "ai")
        remote = FieldVersion("b", datetime(2026, 1, 2), "human")
        df = DeferredField("notes", local, remote, ConflictStrategy.MANUAL_MERGE)
        assert df.field_name == "notes"
        assert df.local.value == "a"
        assert df.remote.value == "b"
        assert df.strategy == ConflictStrategy.MANUAL_MERGE


class TestConflictResult:
    def test_defaults(self):
        cr = ConflictResult()
        assert cr.resolved == ()
        assert cr.deferred == ()

    def test_frozen_immutability(self):
        cr = ConflictResult()
        with pytest.raises(AttributeError):
            cr.resolved = ()


# ---------------------------------------------------------------------------
# ConflictResolver
# ---------------------------------------------------------------------------

class TestConflictResolver:
    """衝突解決器測試 — 覆蓋三種策略、tiebreak、空輸入、unknown entity"""

    @staticmethod
    def _make_resolver() -> ConflictResolver:
        """card: title=LWW, notes=MANUAL_MERGE, default=AI_MERGE"""
        registry = SyncRuleRegistry()
        fr_title = FieldRule(
            "title", SyncDirection.AI_TO_HUMAN,
            ConflictStrategy.LAST_WRITE_WINS, frozenset({"ai"}),
        )
        fr_notes = FieldRule(
            "notes", SyncDirection.BIDIRECTIONAL,
            ConflictStrategy.MANUAL_MERGE, frozenset({"ai", "human"}),
        )
        fr_tags = FieldRule(
            "tags", SyncDirection.BIDIRECTIONAL,
            ConflictStrategy.AI_MERGE, frozenset({"ai", "human"}),
        )
        rule = SyncRule(
            "card", (fr_title, fr_notes, fr_tags),
            SyncDirection.BIDIRECTIONAL, ConflictStrategy.AI_MERGE,
        )
        registry.register(rule)
        return ConflictResolver(registry)

    # -- LAST_WRITE_WINS: local 較新 --
    def test_lww_local_wins(self):
        resolver = self._make_resolver()
        local = {"title": FieldVersion("Local", datetime(2026, 3, 2), "ai")}
        remote = {"title": FieldVersion("Remote", datetime(2026, 3, 1), "human")}
        result = resolver.resolve("card", local, remote)
        assert len(result.resolved) == 1
        assert result.resolved[0].value == "Local"
        assert result.resolved[0].strategy == ConflictStrategy.LAST_WRITE_WINS
        assert len(result.deferred) == 0

    # -- LAST_WRITE_WINS: remote 較新 --
    def test_lww_remote_wins(self):
        resolver = self._make_resolver()
        local = {"title": FieldVersion("Local", datetime(2026, 3, 1), "ai")}
        remote = {"title": FieldVersion("Remote", datetime(2026, 3, 2), "human")}
        result = resolver.resolve("card", local, remote)
        assert result.resolved[0].value == "Remote"

    # -- LAST_WRITE_WINS: tiebreak → remote wins --
    def test_lww_tiebreak_remote_wins(self):
        resolver = self._make_resolver()
        same_time = datetime(2026, 3, 1, 12, 0, 0)
        local = {"title": FieldVersion("Local", same_time, "ai")}
        remote = {"title": FieldVersion("Remote", same_time, "human")}
        result = resolver.resolve("card", local, remote)
        assert result.resolved[0].value == "Remote"

    # -- MANUAL_MERGE → deferred --
    def test_manual_merge_deferred(self):
        resolver = self._make_resolver()
        local = {"notes": FieldVersion("L-note", datetime(2026, 3, 1), "ai")}
        remote = {"notes": FieldVersion("R-note", datetime(2026, 3, 2), "human")}
        result = resolver.resolve("card", local, remote)
        assert len(result.resolved) == 0
        assert len(result.deferred) == 1
        assert result.deferred[0].field_name == "notes"
        assert result.deferred[0].strategy == ConflictStrategy.MANUAL_MERGE
        assert result.deferred[0].local.value == "L-note"
        assert result.deferred[0].remote.value == "R-note"

    # -- AI_MERGE → deferred --
    def test_ai_merge_deferred(self):
        resolver = self._make_resolver()
        local = {"tags": FieldVersion(["a"], datetime(2026, 3, 1), "ai")}
        remote = {"tags": FieldVersion(["b"], datetime(2026, 3, 2), "human")}
        result = resolver.resolve("card", local, remote)
        assert len(result.deferred) == 1
        assert result.deferred[0].field_name == "tags"
        assert result.deferred[0].strategy == ConflictStrategy.AI_MERGE

    # -- 非衝突：只有 local --
    def test_local_only_auto_resolved(self):
        resolver = self._make_resolver()
        local = {"title": FieldVersion("New", datetime(2026, 3, 1), "ai")}
        result = resolver.resolve("card", local, {})
        assert len(result.resolved) == 1
        assert result.resolved[0].value == "New"
        assert len(result.deferred) == 0

    # -- 非衝突：只有 remote --
    def test_remote_only_auto_resolved(self):
        resolver = self._make_resolver()
        remote = {"title": FieldVersion("New", datetime(2026, 3, 1), "human")}
        result = resolver.resolve("card", {}, remote)
        assert len(result.resolved) == 1
        assert result.resolved[0].value == "New"

    # -- 空輸入 --
    def test_empty_inputs(self):
        resolver = self._make_resolver()
        result = resolver.resolve("card", {}, {})
        assert result.resolved == ()
        assert result.deferred == ()

    # -- unknown entity → fallback LWW --
    def test_unknown_entity_fallback_lww(self):
        resolver = self._make_resolver()
        local = {"field": FieldVersion("L", datetime(2026, 3, 2), "ai")}
        remote = {"field": FieldVersion("R", datetime(2026, 3, 1), "human")}
        result = resolver.resolve("unknown", local, remote)
        assert len(result.resolved) == 1
        assert result.resolved[0].value == "L"
        assert result.resolved[0].strategy == ConflictStrategy.LAST_WRITE_WINS

    # -- 混合情境：多欄位同時有衝突與非衝突 --
    def test_mixed_conflict_and_no_conflict(self):
        resolver = self._make_resolver()
        local = {
            "title": FieldVersion("LT", datetime(2026, 3, 2), "ai"),
            "notes": FieldVersion("LN", datetime(2026, 3, 1), "ai"),
        }
        remote = {
            "title": FieldVersion("RT", datetime(2026, 3, 1), "human"),
            "tags": FieldVersion(["t"], datetime(2026, 3, 1), "human"),
        }
        result = resolver.resolve("card", local, remote)
        # title: LWW, local 較新 → resolved
        # notes: local only → resolved
        # tags: remote only → resolved
        assert len(result.resolved) == 3
        assert len(result.deferred) == 0
        resolved_map = {r.field_name: r for r in result.resolved}
        assert resolved_map["title"].value == "LT"
        assert resolved_map["notes"].value == "LN"
        assert resolved_map["tags"].value == ["t"]

    # -- default_strategy fallback（未定義 field_rule 的欄位）--
    def test_default_strategy_fallback(self):
        resolver = self._make_resolver()
        # "description" 不在 field_rules 中 → default_strategy = AI_MERGE → deferred
        local = {"description": FieldVersion("L", datetime(2026, 3, 1), "ai")}
        remote = {"description": FieldVersion("R", datetime(2026, 3, 2), "human")}
        result = resolver.resolve("card", local, remote)
        assert len(result.deferred) == 1
        assert result.deferred[0].field_name == "description"
        assert result.deferred[0].strategy == ConflictStrategy.AI_MERGE
