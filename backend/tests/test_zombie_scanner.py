"""Unit tests for app.jobs.zombie_scanner (Step 1 pure-function scanner)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.jobs.zombie_scanner import (
    ZombieCandidate,
    ZombieRecord,
    list_zombie_cards,
)


def _always_alive(_pid: int) -> bool:
    return True


def _always_dead(_pid: int) -> bool:
    return False


def test_pid_missing_marks_zombie() -> None:
    now = datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc)
    candidates = [
        ZombieCandidate(
            card_id=101,
            worker_pid=None,
            started_at=now - timedelta(minutes=5),
        )
    ]

    records = list_zombie_cards(candidates, now=now, pid_checker=_always_alive)

    assert records == [
        ZombieRecord(card_id=101, worker_pid=None, reason="pid_missing")
    ]


def test_pid_alive_within_window_not_zombie() -> None:
    now = datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc)
    candidates = [
        ZombieCandidate(
            card_id=202,
            worker_pid=4321,
            started_at=now - timedelta(minutes=30),
        )
    ]

    records = list_zombie_cards(
        candidates, now=now, max_hours=2.0, pid_checker=_always_alive
    )

    assert records == []


def test_pid_dead_marks_zombie() -> None:
    now = datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc)
    candidates = [
        ZombieCandidate(
            card_id=303,
            worker_pid=9999,
            started_at=now - timedelta(minutes=10),
        )
    ]

    records = list_zombie_cards(candidates, now=now, pid_checker=_always_dead)

    assert records == [
        ZombieRecord(card_id=303, worker_pid=9999, reason="pid_dead")
    ]


def test_timeout_marks_zombie() -> None:
    now = datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc)
    candidates = [
        ZombieCandidate(
            card_id=404,
            worker_pid=1234,
            started_at=now - timedelta(hours=3),
        )
    ]

    records = list_zombie_cards(
        candidates, now=now, max_hours=2.0, pid_checker=_always_alive
    )

    assert records == [
        ZombieRecord(card_id=404, worker_pid=1234, reason="timeout")
    ]


def test_mixed_candidates_returns_only_zombies() -> None:
    now = datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc)
    alive_pids = {1111}

    def checker(pid: int) -> bool:
        return pid in alive_pids

    candidates = [
        ZombieCandidate(card_id=1, worker_pid=1111, started_at=now - timedelta(minutes=5)),  # healthy
        ZombieCandidate(card_id=2, worker_pid=None, started_at=now - timedelta(minutes=1)),  # pid_missing
        ZombieCandidate(card_id=3, worker_pid=2222, started_at=now - timedelta(minutes=10)),  # pid_dead
        ZombieCandidate(card_id=4, worker_pid=1111, started_at=now - timedelta(hours=5)),    # timeout
    ]

    records = list_zombie_cards(
        candidates, now=now, max_hours=2.0, pid_checker=checker
    )

    assert records == [
        ZombieRecord(card_id=2, worker_pid=None, reason="pid_missing"),
        ZombieRecord(card_id=3, worker_pid=2222, reason="pid_dead"),
        ZombieRecord(card_id=4, worker_pid=1111, reason="timeout"),
    ]


def test_input_list_not_mutated() -> None:
    now = datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc)
    candidates = [
        ZombieCandidate(card_id=1, worker_pid=None, started_at=now),
        ZombieCandidate(card_id=2, worker_pid=1111, started_at=now),
    ]
    snapshot = list(candidates)

    list_zombie_cards(candidates, now=now, pid_checker=_always_alive)

    assert candidates == snapshot
