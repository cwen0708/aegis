"""Tests for app.core.task_tracker.state (P2-MA-14 step 1)."""
from app.core.task_tracker.state import (
    EventRecord,
    RunState,
    add_subscriber,
    append_event,
    create_run,
    remove_subscriber,
)


def _evt(event_type: str = "status", payload: dict | None = None, ts: float = 0.0) -> EventRecord:
    return EventRecord(event_type=event_type, payload=payload or {}, ts=ts)


def test_create_run_starts_with_empty_buffer_and_subscribers():
    state = create_run("run-1")
    assert isinstance(state, RunState)
    assert state.run_key == "run-1"
    assert state.buffer == ()
    assert state.subscriber_ids == ()


def test_append_event_returns_new_state_not_mutating_original():
    original = create_run("run-1")
    event = _evt("status", {"phase": "running"}, ts=1.0)

    updated = append_event(original, event)

    assert updated is not original
    assert original.buffer == ()
    assert updated.buffer == (event,)
    assert updated.run_key == original.run_key


def test_buffer_preserves_insertion_order():
    state = create_run("run-1")
    e1 = _evt("a", {"i": 1}, ts=1.0)
    e2 = _evt("b", {"i": 2}, ts=2.0)
    e3 = _evt("c", {"i": 3}, ts=3.0)

    state = append_event(state, e1)
    state = append_event(state, e2)
    state = append_event(state, e3)

    assert state.buffer == (e1, e2, e3)


def test_add_subscriber_is_idempotent():
    state = create_run("run-1")

    state = add_subscriber(state, "sub-1")
    once = state
    state = add_subscriber(state, "sub-1")

    assert state is once  # 重複加入回傳原物件
    assert state.subscriber_ids == ("sub-1",)


def test_remove_subscriber_is_idempotent():
    state = create_run("run-1")

    result = remove_subscriber(state, "missing")

    assert result is state
    assert result.subscriber_ids == ()


def test_remove_subscriber_returns_state_without_sid():
    state = create_run("run-1")
    state = add_subscriber(state, "sub-1")
    state = add_subscriber(state, "sub-2")
    state = add_subscriber(state, "sub-3")

    updated = remove_subscriber(state, "sub-2")

    assert updated is not state
    assert state.subscriber_ids == ("sub-1", "sub-2", "sub-3")  # 原物件不動
    assert updated.subscriber_ids == ("sub-1", "sub-3")
