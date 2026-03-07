import pytest
from pathlib import Path
from sqlmodel import Session, SQLModel, create_engine


@pytest.fixture
def tmp_project(tmp_path):
    """Create a temporary project directory with .aegis/cards/"""
    cards_dir = tmp_path / ".aegis" / "cards"
    cards_dir.mkdir(parents=True)
    return tmp_path


@pytest.fixture
def db_session(tmp_path):
    """Create a temporary SQLite database session"""
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
