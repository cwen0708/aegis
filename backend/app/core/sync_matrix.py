"""
Sync Matrix Engine — 同步規則引擎核心

定義欄位級同步方向、衝突策略與存取控制的資料模型，
為後續衝突解決和欄位級同步奠定基礎。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class SyncDirection(Enum):
    """同步方向"""

    AI_TO_HUMAN = "ai_to_human"
    HUMAN_TO_AI = "human_to_ai"
    BIDIRECTIONAL = "bidirectional"
    READ_ONLY = "read_only"


class ConflictStrategy(Enum):
    """衝突解決策略"""

    LAST_WRITE_WINS = "last_write_wins"
    MANUAL_MERGE = "manual_merge"
    AI_MERGE = "ai_merge"


@dataclass(frozen=True)
class FieldRule:
    """單一欄位的同步規則"""

    field_name: str
    sync_direction: SyncDirection
    conflict_strategy: ConflictStrategy
    writable_by: frozenset[str]


@dataclass(frozen=True)
class SyncRule:
    """實體層級的同步規則，包含欄位級規則"""

    entity_type: str
    field_rules: tuple[FieldRule, ...]
    default_direction: SyncDirection
    default_strategy: ConflictStrategy


class SyncRuleProvider(Protocol):
    """同步規則提供者介面（Protocol-based 設計）"""

    def get_rule(self, entity_type: str) -> SyncRule | None: ...

    def check_field_writable(
        self, entity_type: str, field_name: str, actor: str,
    ) -> bool: ...

    def list_rules(self) -> list[SyncRule]: ...


class SyncRuleRegistry:
    """同步規則註冊表 — 管理實體類型的同步規則"""

    def __init__(self) -> None:
        self._rules: dict[str, SyncRule] = {}

    def register(self, rule: SyncRule) -> None:
        """註冊同步規則，以 entity_type 為鍵。"""
        self._rules[rule.entity_type] = rule

    def get_rule(self, entity_type: str) -> SyncRule | None:
        """取得指定實體類型的同步規則。"""
        return self._rules.get(entity_type)

    def check_field_writable(
        self, entity_type: str, field_name: str, actor: str,
    ) -> bool:
        """檢查角色是否可寫入特定欄位。

        查詢順序：field_rules 明確規則 -> default_direction fallback。
        """
        rule = self._rules.get(entity_type)
        if rule is None:
            return False

        for fr in rule.field_rules:
            if fr.field_name == field_name:
                return actor in fr.writable_by

        return _direction_allows(rule.default_direction, actor)

    def list_rules(self) -> list[SyncRule]:
        """列出所有已註冊的同步規則。"""
        return list(self._rules.values())


def _direction_allows(direction: SyncDirection, actor: str) -> bool:
    """根據同步方向判斷角色是否可寫入。"""
    if direction == SyncDirection.BIDIRECTIONAL:
        return True
    if direction == SyncDirection.READ_ONLY:
        return False
    if direction == SyncDirection.AI_TO_HUMAN:
        return actor == "ai"
    if direction == SyncDirection.HUMAN_TO_AI:
        return actor == "human"
    return False
