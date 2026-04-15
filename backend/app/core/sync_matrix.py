"""
Sync Matrix Engine — 同步規則引擎核心

定義欄位級同步方向、衝突策略與存取控制的資料模型，
為後續衝突解決和欄位級同步奠定基礎。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Protocol

from fastapi import HTTPException

VALID_ACTORS = frozenset({"ai", "human"})


def validate_actor(actor: str) -> str:
    if actor not in VALID_ACTORS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid actor '{actor}'. Must be one of: {', '.join(sorted(VALID_ACTORS))}",
        )
    return actor


class SyncDirection(Enum):
    """同步方向"""

    AI_TO_HUMAN = "ai_to_human"
    HUMAN_TO_AI = "human_to_ai"
    BIDIRECTIONAL = "bidirectional"
    READ_ONLY = "read_only"


class ConflictStrategy(Enum):
    """衝突解決策略"""

    LAST_WRITE_WINS = "last_write_wins"
    HUMAN_WINS = "human_wins"
    AI_WINS = "ai_wins"
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


@dataclass(frozen=True)
class RejectedField:
    """被拒絕的欄位變更 (field_name, reason) 對"""

    field_name: str
    reason: str


@dataclass(frozen=True)
class ValidatedChanges:
    """通過驗證的欄位變更結果"""

    approved: dict[str, Any] = field(default_factory=dict)
    rejected: tuple[RejectedField, ...] = ()


@dataclass(frozen=True)
class FieldVersion:
    """欄位版本快照 — 記錄值、更新時間與操作者"""

    value: Any
    updated_at: datetime
    actor: str


@dataclass(frozen=True)
class ResolvedField:
    """已解決的衝突欄位"""

    field_name: str
    value: Any
    strategy: ConflictStrategy


@dataclass(frozen=True)
class DeferredField:
    """需人工或 AI 介入的延遲衝突欄位"""

    field_name: str
    local: FieldVersion
    remote: FieldVersion
    strategy: ConflictStrategy


@dataclass(frozen=True)
class ConflictResult:
    """衝突解決結果 — resolved 為已自動解決，deferred 為待處理"""

    resolved: tuple[ResolvedField, ...] = ()
    deferred: tuple[DeferredField, ...] = ()


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


class SyncEnforcer:
    """同步強制器 — 基於 SyncRuleProvider 在寫入時驗證欄位級存取權限"""

    def __init__(self, provider: SyncRuleProvider) -> None:
        self._provider = provider

    def validate(
        self, entity_type: str, changes: dict[str, Any], actor: str,
    ) -> ValidatedChanges:
        """逐欄位檢查 writable 權限，回傳驗證結果。"""
        approved: dict[str, Any] = {}
        rejected: list[RejectedField] = []

        for field_name, value in changes.items():
            if self._provider.check_field_writable(entity_type, field_name, actor):
                approved[field_name] = value
            else:
                rejected.append(
                    RejectedField(
                        field_name=field_name,
                        reason=f"actor '{actor}' cannot write field '{field_name}' on '{entity_type}'",
                    ),
                )

        return ValidatedChanges(approved=approved, rejected=tuple(rejected))

    def enforce(
        self, entity_type: str, changes: dict[str, Any], actor: str,
    ) -> dict[str, Any]:
        """過濾掉被拒欄位，只回傳允許的變更（新 dict，不修改原 changes）。"""
        result = self.validate(entity_type, changes, actor)
        return dict(result.approved)


class ConflictResolver:
    """衝突解決器 — 根據 FieldRule 的 conflict_strategy 偵測並解決欄位級衝突"""

    def __init__(self, provider: SyncRuleProvider) -> None:
        self._provider = provider

    def resolve(
        self,
        entity_type: str,
        local_changes: dict[str, FieldVersion],
        remote_changes: dict[str, FieldVersion],
    ) -> ConflictResult:
        """偵測並解決 local 與 remote 之間的欄位級衝突。

        - 僅出現在一方的欄位自動 resolve（取該方的值）
        - 雙方都有的欄位依策略處理：
          - LAST_WRITE_WINS: 比較 updated_at，取較新者；相同時 remote wins
          - MANUAL_MERGE / AI_MERGE: 放入 deferred
        """
        rule = self._provider.get_rule(entity_type)

        all_fields = set(local_changes) | set(remote_changes)
        resolved: list[ResolvedField] = []
        deferred: list[DeferredField] = []

        for field_name in sorted(all_fields):
            local_ver = local_changes.get(field_name)
            remote_ver = remote_changes.get(field_name)
            strategy = _field_strategy(rule, field_name)

            # 非衝突：只有一方有變更 → 自動 resolve
            if local_ver is None and remote_ver is not None:
                resolved.append(
                    ResolvedField(field_name, remote_ver.value, strategy),
                )
                continue
            if remote_ver is None and local_ver is not None:
                resolved.append(
                    ResolvedField(field_name, local_ver.value, strategy),
                )
                continue

            # 雙方都有變更 → 根據策略處理
            assert local_ver is not None and remote_ver is not None
            if strategy == ConflictStrategy.LAST_WRITE_WINS:
                winner = (
                    remote_ver
                    if remote_ver.updated_at >= local_ver.updated_at
                    else local_ver
                )
                resolved.append(
                    ResolvedField(field_name, winner.value, strategy),
                )
            elif strategy == ConflictStrategy.HUMAN_WINS:
                winner = _actor_priority_winner(
                    local_ver, remote_ver, preferred="human",
                )
                resolved.append(
                    ResolvedField(field_name, winner.value, strategy),
                )
            elif strategy == ConflictStrategy.AI_WINS:
                winner = _actor_priority_winner(
                    local_ver, remote_ver, preferred="ai",
                )
                resolved.append(
                    ResolvedField(field_name, winner.value, strategy),
                )
            else:
                # MANUAL_MERGE / AI_MERGE → deferred
                deferred.append(
                    DeferredField(field_name, local_ver, remote_ver, strategy),
                )

        return ConflictResult(
            resolved=tuple(resolved),
            deferred=tuple(deferred),
        )


def _actor_priority_winner(
    local: FieldVersion, remote: FieldVersion, *, preferred: str,
) -> FieldVersion:
    """依 actor 優先級選出勝方。

    - 若其中一方的 actor 為 preferred，該方勝出
    - 若雙方 actor 相同（無法區分優先級），退化為 last_write_wins
    """
    if local.actor == remote.actor:
        return remote if remote.updated_at >= local.updated_at else local
    if local.actor == preferred:
        return local
    return remote


def _field_strategy(rule: SyncRule | None, field_name: str) -> ConflictStrategy:
    """取得欄位的衝突策略：field_rules 明確規則 -> default_strategy fallback。"""
    if rule is None:
        return ConflictStrategy.LAST_WRITE_WINS

    for fr in rule.field_rules:
        if fr.field_name == field_name:
            return fr.conflict_strategy

    return rule.default_strategy


def _writable_to_set(writable_by: str) -> frozenset[str]:
    """DB writable_by ('ai'/'human'/'both') → frozenset of actor strings。"""
    if writable_by == "both":
        return frozenset({"ai", "human"})
    if writable_by in ("ai", "human"):
        return frozenset({writable_by})
    return frozenset()


def _writable_to_direction(writable_by: str) -> SyncDirection:
    """DB writable_by → SyncDirection enum。"""
    if writable_by == "ai":
        return SyncDirection.AI_TO_HUMAN
    if writable_by == "human":
        return SyncDirection.HUMAN_TO_AI
    return SyncDirection.BIDIRECTIONAL


_SYNC_DIRECTION_MAP: dict[str, SyncDirection] = {
    "ai_to_human": SyncDirection.AI_TO_HUMAN,
    "human_to_ai": SyncDirection.HUMAN_TO_AI,
    "bidirectional": SyncDirection.BIDIRECTIONAL,
    "read_only": SyncDirection.READ_ONLY,
}


def _derive_direction(writable_by: str, sync_direction: str | None) -> SyncDirection:
    """DB sync_direction 有值時直接映射；None 時從 writable_by 推導（向後相容）。"""
    if sync_direction is not None:
        mapped = _SYNC_DIRECTION_MAP.get(sync_direction)
        if mapped is not None:
            return mapped
    return _writable_to_direction(writable_by)


def _db_strategy_to_enum(strategy: str) -> ConflictStrategy:
    """DB conflict_strategy 字串 → ConflictStrategy enum。"""
    _MAP = {
        "last_write_wins": ConflictStrategy.LAST_WRITE_WINS,
        "human_wins": ConflictStrategy.HUMAN_WINS,
        "ai_wins": ConflictStrategy.AI_WINS,
        "manual_merge": ConflictStrategy.MANUAL_MERGE,
        "ai_merge": ConflictStrategy.AI_MERGE,
    }
    return _MAP.get(strategy, ConflictStrategy.LAST_WRITE_WINS)


def load_registry_from_db(session: "Session") -> SyncRuleRegistry:
    """從 DB 載入所有啟用的 SyncRule，轉換為 SyncRuleRegistry。

    Parameters:
        session: SQLModel Session

    Returns:
        填充好的 SyncRuleRegistry
    """
    from sqlmodel import select
    from app.models.core import SyncRule as SyncRuleModel

    rules = session.exec(
        select(SyncRuleModel).where(SyncRuleModel.is_enabled == True)  # noqa: E712
    ).all()

    # 按 entity_type 分組
    grouped: dict[str, list] = {}
    for r in rules:
        grouped.setdefault(r.entity_type, []).append(r)

    registry = SyncRuleRegistry()
    for entity_type, db_rules in grouped.items():
        field_rules = tuple(
            FieldRule(
                field_name=r.field_name,
                sync_direction=_derive_direction(r.writable_by, r.sync_direction),
                conflict_strategy=_db_strategy_to_enum(r.conflict_strategy),
                writable_by=_writable_to_set(r.writable_by),
            )
            for r in db_rules
        )
        registry.register(SyncRule(
            entity_type=entity_type,
            field_rules=field_rules,
            default_direction=SyncDirection.BIDIRECTIONAL,
            default_strategy=ConflictStrategy.LAST_WRITE_WINS,
        ))

    return registry


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
