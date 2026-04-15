"""Tests for Member SyncEnforcement — 驗證 member entity type 的欄位級寫入權限。"""
import pytest

from app.core.sync_matrix import (
    ConflictStrategy,
    FieldRule,
    SyncDirection,
    SyncEnforcer,
    SyncRule,
    SyncRuleRegistry,
)


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
    registry.register(SyncRule(
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
