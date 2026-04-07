"""Tests for Room layout_type Literal validation."""
import pytest
import httpx
from pydantic import ValidationError
from sqlmodel import Session, SQLModel, create_engine

from app.api.messaging import RoomCreate, RoomUpdate


# ------------------------------------------------------------------
# Schema-level validation
# ------------------------------------------------------------------

class TestRoomCreateSchema:
    def test_accepts_tiled(self):
        rc = RoomCreate(name="R1", layout_type="tiled")
        assert rc.layout_type == "tiled"

    def test_accepts_classic(self):
        rc = RoomCreate(name="R1", layout_type="classic")
        assert rc.layout_type == "classic"

    def test_default_is_tiled(self):
        rc = RoomCreate(name="R1")
        assert rc.layout_type == "tiled"

    def test_rejects_invalid(self):
        with pytest.raises(ValidationError):
            RoomCreate(name="R1", layout_type="invalid_type")


class TestRoomUpdateSchema:
    def test_accepts_none(self):
        ru = RoomUpdate()
        assert ru.layout_type is None

    def test_accepts_tiled(self):
        ru = RoomUpdate(layout_type="tiled")
        assert ru.layout_type == "tiled"

    def test_accepts_classic(self):
        ru = RoomUpdate(layout_type="classic")
        assert ru.layout_type == "classic"

    def test_rejects_invalid(self):
        with pytest.raises(ValidationError):
            RoomUpdate(layout_type="invalid_type")


# ------------------------------------------------------------------
# API-level validation (422 on invalid layout_type)
# ------------------------------------------------------------------

@pytest.fixture
async def client(tmp_path):
    """Build an async httpx client backed by a temporary SQLite DB."""
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    SQLModel.metadata.create_all(engine)

    from app.main import app
    from app.database import get_session

    def _override():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = _override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


class TestCreateRoomAPI:
    async def test_invalid_layout_type_returns_422(self, client):
        resp = await client.post("/api/v1/rooms", json={"name": "Bad", "layout_type": "nope"})
        assert resp.status_code == 422


class TestUpdateRoomAPI:
    async def test_invalid_layout_type_returns_422(self, client):
        # Create a valid room first
        create_resp = await client.post("/api/v1/rooms", json={"name": "Good"})
        assert create_resp.status_code == 200
        room_id = create_resp.json()["id"]

        resp = await client.patch(f"/api/v1/rooms/{room_id}", json={"layout_type": "nope"})
        assert resp.status_code == 422
