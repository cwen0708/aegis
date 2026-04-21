"""Branch dispatcher — 跨 chat_key/member 的並行分支調度（純函式骨架）。

不同於 `app.core.session_pool.ProcessPool`（單一 chat_key 持久 CLI 進程），
本模組處理「一張 card 派給多個 member」的並行分支上限與 reserve-before-spawn。

此為 step 1 純函式骨架：不接 asyncio、不接 threading、不接任何 I/O。
實際 dispatch 執行器留給 step 2；TOCTOU 防護留給 step 3。

參考：G:/vendor/Spacebot/src/agent/channel_dispatch.rs §spawn_branch。
"""
from dataclasses import dataclass
from typing import NewType, Optional


BranchId = NewType("BranchId", str)


@dataclass(frozen=True)
class BranchLimitConfig:
    """分支調度的並行上限設定。

    max_branches: 同時活躍的 branch 數量上限（單 card 可派給多少 member）
    max_workers:  每個 branch 底下的 worker 上限（留給 step 2 使用）
    """
    max_branches: int = 5
    max_workers: int = 5


@dataclass(frozen=True)
class BranchLimitError:
    """分支達到上限無法再 reserve 時回傳的錯誤資訊。"""
    reason: str
    active_count: int
    limit: int


def check_branch_limit(
    active_ids: frozenset[BranchId],
    cfg: BranchLimitConfig,
) -> Optional[BranchLimitError]:
    """檢查目前活躍分支是否已達上限。未達上限回傳 None，達上限回傳錯誤物件。

    純函式：不修改 active_ids。
    """
    active_count = len(active_ids)
    if active_count >= cfg.max_branches:
        return BranchLimitError(
            reason="branch_limit_reached",
            active_count=active_count,
            limit=cfg.max_branches,
        )
    return None


def reserve_branch(
    active_ids: frozenset[BranchId],
    new_id: BranchId,
    cfg: BranchLimitConfig,
) -> tuple[frozenset[BranchId], Optional[BranchLimitError]]:
    """保留一個新分支名額。

    成功：回傳 (含 new_id 的新 frozenset, None)
    失敗：回傳 (原 active_ids, BranchLimitError)

    純函式：絕不修改輸入的 active_ids。
    """
    error = check_branch_limit(active_ids, cfg)
    if error is not None:
        return active_ids, error
    return active_ids | {new_id}, None


def release_branch(
    active_ids: frozenset[BranchId],
    branch_id: BranchId,
) -> frozenset[BranchId]:
    """釋放一個分支名額。

    若 branch_id 不在 active_ids 中，原樣回傳（idempotent，不拋例外）。
    純函式：絕不修改輸入的 active_ids。
    """
    if branch_id not in active_ids:
        return active_ids
    return active_ids - {branch_id}
