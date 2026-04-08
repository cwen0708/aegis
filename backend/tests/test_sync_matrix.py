"""Tests for Sync Matrix Engine."""
import pytest

from app.core.sync_matrix import (
    ConflictStrategy,
    FieldRule,
    SyncDirection,
    SyncRule,
    SyncRuleRegistry,
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
