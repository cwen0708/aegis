"""Tests for app.core.matrix (P1-MA-05 step 1).

本測試只驗證骨架行為：
- Pydantic 模型的 enum 值、必要欄位、序列化、不可變性
- NoopMatrixClient 回空字串且不拋例外
- 介面輸入不被 mutate
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.matrix.client import MatrixClient, NoopMatrixClient
from app.core.matrix.models import MatrixMessage, MatrixRoom, RoomKind


# ── RoomKind ─────────────────────────────────────────────────────────────────

def test_room_kind_values_are_stable_strings():
    assert RoomKind.WORKER.value == "worker"
    assert RoomKind.TEAM_WORKER.value == "team_worker"
    assert RoomKind.TEAM.value == "team"


def test_room_kind_str_enum_equals_raw_value():
    # str(Enum) 在不同版本行為不一，但 .value 必須等於字串；存回 JSON 也只需字串。
    assert RoomKind("worker") is RoomKind.WORKER
    assert RoomKind("team_worker") is RoomKind.TEAM_WORKER
    assert RoomKind("team") is RoomKind.TEAM


def test_room_kind_rejects_unknown_value():
    with pytest.raises(ValueError):
        RoomKind("admin_only")


# ── MatrixRoom ───────────────────────────────────────────────────────────────

def test_matrix_room_minimal_construction_ok():
    room = MatrixRoom(
        room_id="!abc:matrix.org",
        kind=RoomKind.WORKER,
        meeting_ref="meeting-42",
    )
    assert room.room_id == "!abc:matrix.org"
    assert room.kind is RoomKind.WORKER
    assert room.meeting_ref == "meeting-42"
    assert room.members == []
    assert room.topic == ""


def test_matrix_room_accepts_empty_members_list():
    # 剛建立尚未 invite 的情境應可接受。
    room = MatrixRoom(
        room_id="!r:s",
        kind=RoomKind.TEAM,
        meeting_ref="m1",
        members=[],
    )
    assert room.members == []


def test_matrix_room_requires_room_id_and_meeting_ref():
    with pytest.raises(ValidationError):
        MatrixRoom(room_id="", kind=RoomKind.WORKER, meeting_ref="m1")
    with pytest.raises(ValidationError):
        MatrixRoom(room_id="!r:s", kind=RoomKind.WORKER, meeting_ref="")


def test_matrix_room_rejects_extra_fields():
    with pytest.raises(ValidationError):
        MatrixRoom(
            room_id="!r:s",
            kind=RoomKind.WORKER,
            meeting_ref="m1",
            unknown_field=True,  # type: ignore[call-arg]
        )


def test_matrix_room_is_frozen():
    room = MatrixRoom(room_id="!r:s", kind=RoomKind.WORKER, meeting_ref="m1")
    with pytest.raises(ValidationError):
        room.topic = "new topic"  # type: ignore[misc]


def test_matrix_room_roundtrip_dump_and_validate():
    room = MatrixRoom(
        room_id="!r:s",
        kind=RoomKind.TEAM_WORKER,
        meeting_ref="m1",
        members=["xiao-yin", "xiao-mu"],
        topic="demo",
    )
    data = room.model_dump()
    assert data["kind"] == "team_worker"
    restored = MatrixRoom.model_validate(data)
    assert restored == room
    assert restored is not room


# ── MatrixMessage ────────────────────────────────────────────────────────────

def test_matrix_message_defaults_to_m_text():
    msg = MatrixMessage(room_id="!r:s", sender="xiao-yin")
    assert msg.msgtype == "m.text"
    assert msg.body == ""


def test_matrix_message_requires_room_id_and_sender():
    with pytest.raises(ValidationError):
        MatrixMessage(room_id="", sender="xiao-yin")
    with pytest.raises(ValidationError):
        MatrixMessage(room_id="!r:s", sender="")


def test_matrix_message_rejects_unknown_msgtype():
    with pytest.raises(ValidationError):
        MatrixMessage(room_id="!r:s", sender="xiao-yin", msgtype="m.image")  # type: ignore[arg-type]


def test_matrix_message_is_frozen():
    msg = MatrixMessage(room_id="!r:s", sender="xiao-yin", body="hi")
    with pytest.raises(ValidationError):
        msg.body = "changed"  # type: ignore[misc]


# ── NoopMatrixClient ─────────────────────────────────────────────────────────

def test_noop_client_implements_matrix_client_protocol():
    assert isinstance(NoopMatrixClient(), MatrixClient)


def test_noop_create_room_returns_empty_string_and_does_not_raise():
    client = NoopMatrixClient()
    room = MatrixRoom(
        room_id="!r:s",
        kind=RoomKind.WORKER,
        meeting_ref="meeting-1",
        members=["leader", "admin", "xiao-yin"],
    )
    assert client.create_room(room) == ""


def test_noop_send_message_returns_empty_string_and_does_not_raise():
    client = NoopMatrixClient()
    msg = MatrixMessage(room_id="!r:s", sender="xiao-yin", body="hello")
    assert client.send_message(msg) == ""


def test_noop_create_room_does_not_mutate_input():
    client = NoopMatrixClient()
    members = ["a", "b"]
    room = MatrixRoom(
        room_id="!r:s",
        kind=RoomKind.TEAM,
        meeting_ref="m1",
        members=members,
    )
    snapshot = room.model_dump()
    client.create_room(room)
    # 模型 frozen + 傳入 list 不被 client 改動
    assert room.model_dump() == snapshot
    assert members == ["a", "b"]


def test_noop_send_message_does_not_mutate_input():
    client = NoopMatrixClient()
    msg = MatrixMessage(room_id="!r:s", sender="xiao-yin", body="hi")
    snapshot = msg.model_dump()
    client.send_message(msg)
    assert msg.model_dump() == snapshot
