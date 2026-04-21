"""branch_dispatcher 純函式單元測試（無 mock、無 sleep、無 I/O）。"""
from app.executor.branch_dispatcher import (
    BranchId,
    BranchLimitConfig,
    BranchLimitError,
    check_branch_limit,
    release_branch,
    reserve_branch,
)


def test_check_limit_under():
    active = frozenset({BranchId("a"), BranchId("b")})
    cfg = BranchLimitConfig(max_branches=5)
    assert check_branch_limit(active, cfg) is None


def test_check_limit_at_cap():
    active = frozenset({BranchId(f"b{i}") for i in range(5)})
    cfg = BranchLimitConfig(max_branches=5)
    err = check_branch_limit(active, cfg)
    assert isinstance(err, BranchLimitError)
    assert err.active_count == 5
    assert err.limit == 5
    assert err.reason == "branch_limit_reached"


def test_reserve_success():
    active = frozenset({BranchId("a")})
    cfg = BranchLimitConfig(max_branches=3)
    new_set, err = reserve_branch(active, BranchId("b"), cfg)
    assert err is None
    assert len(new_set) == len(active) + 1
    assert BranchId("b") in new_set


def test_reserve_full():
    active = frozenset({BranchId(f"b{i}") for i in range(5)})
    cfg = BranchLimitConfig(max_branches=5)
    new_set, err = reserve_branch(active, BranchId("new"), cfg)
    assert err is not None
    assert new_set == active
    assert BranchId("new") not in new_set


def test_release_existing():
    active = frozenset({BranchId("a"), BranchId("b")})
    new_set = release_branch(active, BranchId("a"))
    assert len(new_set) == len(active) - 1
    assert BranchId("a") not in new_set
    assert BranchId("b") in new_set


def test_release_missing():
    active = frozenset({BranchId("a")})
    new_set = release_branch(active, BranchId("not-there"))
    assert new_set == active


def test_immutability():
    """呼叫純函式後，原輸入 frozenset 的 id() 不變。"""
    original = frozenset({BranchId("a"), BranchId("b")})
    original_id = id(original)
    cfg = BranchLimitConfig(max_branches=3)

    check_branch_limit(original, cfg)
    reserve_branch(original, BranchId("c"), cfg)
    release_branch(original, BranchId("a"))
    release_branch(original, BranchId("missing"))

    assert id(original) == original_id
    assert original == frozenset({BranchId("a"), BranchId("b")})
