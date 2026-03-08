# MD-Driven Tasks Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Convert Aegis card storage from SQLite-only to MD files as source of truth with SQLite as cache index, plus AEGIS system project with memory.

**Architecture:** Each card becomes a `.md` file with YAML frontmatter in `{Project.path}/.aegis/cards/`. A `CardIndex` table in the central `local.db` caches metadata for fast queries. All card writes go through `card_file.py` (atomic write) + `card_index.py` (index sync). A file watcher detects external edits.

**Tech Stack:** Python 3.12, FastAPI, SQLModel, python-frontmatter, watchfiles, pytest

**Design Doc:** `docs/plans/2026-03-06-md-driven-tasks-design.md`

---

## Phase 1: Foundation (sequential — blocks everything else)

### Task 1: Test Infrastructure + Dependencies

**Files:**
- Modify: `backend/requirements.txt`
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/conftest.py`
- Create: `backend/pytest.ini`

**Step 1: Add dependencies to requirements.txt**

Append to `backend/requirements.txt`:
```
python-frontmatter>=1.1.0
pytest>=8.0.0
pytest-asyncio>=0.23.0
```

**Step 2: Install**

Run: `cd backend && venv/Scripts/pip install -r requirements.txt`

**Step 3: Create test infrastructure**

`backend/pytest.ini`:
```ini
[pytest]
testpaths = tests
asyncio_mode = auto
```

`backend/tests/__init__.py`: empty file

`backend/tests/conftest.py`:
```python
import os
import tempfile
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
```

**Step 4: Verify pytest runs**

Run: `cd backend && python -m pytest tests/ -v`
Expected: `no tests ran` (0 collected, no errors)

**Step 5: Commit**

```bash
git add backend/requirements.txt backend/tests/ backend/pytest.ini
git commit -m "chore: add test infrastructure and python-frontmatter dependency"
```

---

### Task 2: CardData Model + card_file.py (read/write engine)

**Files:**
- Create: `backend/app/core/card_file.py`
- Create: `backend/tests/test_card_file.py`

**Step 1: Write failing tests**

`backend/tests/test_card_file.py`:
```python
import pytest
from pathlib import Path
from datetime import datetime, timezone
from app.core.card_file import (
    CardData, read_card, write_card, card_file_path,
    serialize_card, validate_frontmatter, VALID_STATUSES
)

# ── Serialize / Deserialize ──

def test_roundtrip(tmp_project):
    """Write a card, read it back, all fields match."""
    card = CardData(
        id=42,
        list_id=5,
        title="Fix SQLite pool",
        description="Serious bug",
        content="## Details\n\nSome markdown content.",
        status="idle",
        tags=["Bug", "Backend"],
        created_at=datetime(2026, 3, 7, 12, 0, 0, tzinfo=timezone.utc),
        updated_at=datetime(2026, 3, 7, 12, 0, 0, tzinfo=timezone.utc),
    )
    fpath = card_file_path(str(tmp_project), 42)
    write_card(fpath, card)
    loaded = read_card(fpath)

    assert loaded.id == 42
    assert loaded.list_id == 5
    assert loaded.title == "Fix SQLite pool"
    assert loaded.description == "Serious bug"
    assert loaded.content == "## Details\n\nSome markdown content."
    assert loaded.status == "idle"
    assert loaded.tags == ["Bug", "Backend"]

def test_card_file_path(tmp_project):
    fpath = card_file_path(str(tmp_project), 42)
    assert fpath == tmp_project / ".aegis" / "cards" / "card-000042.md"

def test_empty_content(tmp_project):
    """Card with no body content."""
    card = CardData(
        id=1, list_id=1, title="Empty", description=None,
        content="", status="idle", tags=[],
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    fpath = card_file_path(str(tmp_project), 1)
    write_card(fpath, card)
    loaded = read_card(fpath)
    assert loaded.content == ""
    assert loaded.description is None

def test_atomic_write_no_partial(tmp_project):
    """If write_card succeeds, .md.tmp should not exist."""
    card = CardData(
        id=1, list_id=1, title="Test", description=None,
        content="body", status="idle", tags=[],
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    fpath = card_file_path(str(tmp_project), 1)
    write_card(fpath, card)
    assert not fpath.with_suffix(".md.tmp").exists()
    assert fpath.exists()

# ── Validation ──

def test_validate_valid():
    data = {"id": 1, "list_id": 1, "title": "X", "status": "idle"}
    assert validate_frontmatter(data) == []

def test_validate_missing_id():
    data = {"list_id": 1, "title": "X", "status": "idle"}
    errors = validate_frontmatter(data)
    assert any("id" in e for e in errors)

def test_validate_bad_status():
    data = {"id": 1, "list_id": 1, "title": "X", "status": "bogus"}
    errors = validate_frontmatter(data)
    assert any("status" in e for e in errors)

# ── Edge cases ──

def test_special_chars_in_title(tmp_project):
    """Titles with YAML-special chars survive roundtrip."""
    card = CardData(
        id=2, list_id=1,
        title='Fix "colon: issue" & <angle>',
        description="desc: with colon",
        content="body", status="idle", tags=["tag: special"],
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    fpath = card_file_path(str(tmp_project), 2)
    write_card(fpath, card)
    loaded = read_card(fpath)
    assert loaded.title == card.title
    assert loaded.description == card.description
    assert loaded.tags == card.tags
```

**Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_card_file.py -v`
Expected: FAIL (ImportError — module doesn't exist yet)

**Step 3: Implement card_file.py**

`backend/app/core/card_file.py`:
```python
"""MD file read/write engine for card data."""
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import frontmatter

VALID_STATUSES = {"idle", "pending", "running", "completed", "failed"}


@dataclass
class CardData:
    """Card data structure (independent of SQLModel ORM)."""
    id: int
    list_id: int
    title: str
    description: Optional[str]
    content: str
    status: str
    tags: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def card_file_path(project_path: str, card_id: int) -> Path:
    """Return path: {project_path}/.aegis/cards/card-{id:06d}.md"""
    return Path(project_path) / ".aegis" / "cards" / f"card-{card_id:06d}.md"


def serialize_card(card: CardData) -> str:
    """Serialize CardData to frontmatter + markdown body string."""
    metadata = {
        "id": card.id,
        "list_id": card.list_id,
        "title": card.title,
        "description": card.description,
        "status": card.status,
        "tags": card.tags,
        "created_at": card.created_at.isoformat(),
        "updated_at": card.updated_at.isoformat(),
    }
    post = frontmatter.Post(card.content, **metadata)
    return frontmatter.dumps(post) + "\n"


def write_card(file_path: Path, card: CardData) -> None:
    """Atomic write: temp -> fsync -> rename."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = file_path.with_suffix(".md.tmp")
    content = serialize_card(card)
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(file_path)


def read_card(file_path: Path) -> CardData:
    """Parse MD file -> CardData. Raises ValueError on invalid frontmatter."""
    post = frontmatter.load(str(file_path))
    meta = post.metadata
    errors = validate_frontmatter(meta)
    if errors:
        raise ValueError(f"Invalid frontmatter in {file_path}: {errors}")

    def parse_dt(val):
        if isinstance(val, datetime):
            return val
        return datetime.fromisoformat(str(val))

    return CardData(
        id=meta["id"],
        list_id=meta["list_id"],
        title=meta["title"],
        description=meta.get("description"),
        content=post.content,
        status=meta["status"],
        tags=meta.get("tags", []),
        created_at=parse_dt(meta.get("created_at", datetime.now(timezone.utc))),
        updated_at=parse_dt(meta.get("updated_at", datetime.now(timezone.utc))),
    )


def validate_frontmatter(data: dict) -> list[str]:
    """Validate required frontmatter fields. Returns list of error messages."""
    errors = []
    if "id" not in data or not isinstance(data["id"], int):
        errors.append("missing or invalid 'id' (must be int)")
    if "list_id" not in data or not isinstance(data["list_id"], int):
        errors.append("missing or invalid 'list_id' (must be int)")
    if "title" not in data or not isinstance(data["title"], str):
        errors.append("missing or invalid 'title' (must be str)")
    if data.get("status") not in VALID_STATUSES:
        errors.append(f"invalid 'status': {data.get('status')}")
    return errors
```

**Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_card_file.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add backend/app/core/card_file.py backend/tests/test_card_file.py
git commit -m "feat: card_file.py — MD read/write engine with atomic writes"
```

---

### Task 3: CardIndex model + card_index.py

**Files:**
- Modify: `backend/app/models/core.py` (add CardIndex table)
- Create: `backend/app/core/card_index.py`
- Create: `backend/tests/test_card_index.py`

**Step 1: Add CardIndex model to core.py**

Add after the `Card` class in `backend/app/models/core.py`:

```python
class CardIndex(SQLModel, table=True):
    """SQLite cache index for MD card files — NOT source of truth."""
    card_id: int = Field(primary_key=True)
    project_id: int = Field(index=True)
    file_path: str = ""
    list_id: int = Field(default=0, index=True)
    status: str = Field(default="idle", index=True)
    title: str = ""
    description: Optional[str] = None
    tags_json: str = Field(default="[]")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    content_hash: str = ""
    file_mtime: float = Field(default=0.0)
```

**Step 2: Write failing tests**

`backend/tests/test_card_index.py`:
```python
import json
import pytest
from pathlib import Path
from datetime import datetime, timezone
from sqlmodel import Session, select
from app.models.core import CardIndex, Project, StageList
from app.core.card_file import CardData, write_card, card_file_path
from app.core.card_index import (
    sync_card_to_index,
    remove_card_from_index,
    query_pending_cards,
    query_board,
    rebuild_index,
    next_card_id,
)

def _make_card(id, list_id=1, status="idle", title="Test", tags=None):
    return CardData(
        id=id, list_id=list_id, title=title, description="desc",
        content="body", status=status, tags=tags or [],
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

def test_sync_and_query(db_session, tmp_project):
    card = _make_card(1, status="pending", tags=["Bug"])
    fpath = card_file_path(str(tmp_project), 1)
    write_card(fpath, card)
    sync_card_to_index(db_session, card, project_id=1, file_path=str(fpath))
    db_session.commit()

    results = query_pending_cards(db_session)
    assert len(results) == 1
    assert results[0].card_id == 1
    assert results[0].status == "pending"
    assert json.loads(results[0].tags_json) == ["Bug"]

def test_remove_from_index(db_session, tmp_project):
    card = _make_card(1)
    fpath = card_file_path(str(tmp_project), 1)
    write_card(fpath, card)
    sync_card_to_index(db_session, card, project_id=1, file_path=str(fpath))
    db_session.commit()

    remove_card_from_index(db_session, card_id=1)
    db_session.commit()

    idx = db_session.get(CardIndex, 1)
    assert idx is None

def test_query_board(db_session, tmp_project):
    for i in range(3):
        card = _make_card(i + 1, list_id=10, status="idle", title=f"Card {i}")
        fpath = card_file_path(str(tmp_project), i + 1)
        write_card(fpath, card)
        sync_card_to_index(db_session, card, project_id=1, file_path=str(fpath))
    db_session.commit()

    results = query_board(db_session, project_id=1)
    assert len(results) == 3

def test_rebuild_index(db_session, tmp_project):
    for i in range(3):
        card = _make_card(i + 1, list_id=5)
        write_card(card_file_path(str(tmp_project), i + 1), card)

    count = rebuild_index(db_session, project_id=1, project_path=str(tmp_project))
    db_session.commit()
    assert count == 3
    assert db_session.get(CardIndex, 1) is not None
    assert db_session.get(CardIndex, 3) is not None

def test_next_card_id_empty(db_session):
    assert next_card_id(db_session) == 1

def test_next_card_id_increments(db_session, tmp_project):
    card = _make_card(42)
    fpath = card_file_path(str(tmp_project), 42)
    write_card(fpath, card)
    sync_card_to_index(db_session, card, project_id=1, file_path=str(fpath))
    db_session.commit()
    assert next_card_id(db_session) == 43
```

**Step 3: Implement card_index.py**

`backend/app/core/card_index.py`:
```python
"""SQLite index cache management for MD card files."""
import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone
from sqlmodel import Session, select, func
from app.models.core import CardIndex
from app.core.card_file import CardData, read_card, validate_frontmatter


def sync_card_to_index(
    session: Session,
    card: CardData,
    project_id: int,
    file_path: str,
) -> None:
    """Upsert a single card's metadata into the index."""
    fpath = Path(file_path)
    mtime = fpath.stat().st_mtime if fpath.exists() else 0.0
    content_hash = hashlib.sha256(fpath.read_bytes()).hexdigest() if fpath.exists() else ""

    existing = session.get(CardIndex, card.id)
    if existing:
        existing.project_id = project_id
        existing.file_path = file_path
        existing.list_id = card.list_id
        existing.status = card.status
        existing.title = card.title
        existing.description = card.description
        existing.tags_json = json.dumps(card.tags, ensure_ascii=False)
        existing.created_at = card.created_at
        existing.updated_at = card.updated_at
        existing.content_hash = content_hash
        existing.file_mtime = mtime
        session.add(existing)
    else:
        idx = CardIndex(
            card_id=card.id,
            project_id=project_id,
            file_path=file_path,
            list_id=card.list_id,
            status=card.status,
            title=card.title,
            description=card.description,
            tags_json=json.dumps(card.tags, ensure_ascii=False),
            created_at=card.created_at,
            updated_at=card.updated_at,
            content_hash=content_hash,
            file_mtime=mtime,
        )
        session.add(idx)


def remove_card_from_index(session: Session, card_id: int) -> None:
    """Remove a card from the index."""
    idx = session.get(CardIndex, card_id)
    if idx:
        session.delete(idx)


def query_pending_cards(session: Session, project_id: int = None) -> list[CardIndex]:
    """Query cards with status='pending'."""
    stmt = select(CardIndex).where(CardIndex.status == "pending")
    if project_id is not None:
        stmt = stmt.where(CardIndex.project_id == project_id)
    return list(session.exec(stmt).all())


def query_board(session: Session, project_id: int) -> list[CardIndex]:
    """Query all cards for a project (for board display)."""
    stmt = select(CardIndex).where(CardIndex.project_id == project_id)
    return list(session.exec(stmt).all())


def rebuild_index(session: Session, project_id: int, project_path: str) -> int:
    """Scan all MD files in project and rebuild index. Returns card count."""
    cards_dir = Path(project_path) / ".aegis" / "cards"
    if not cards_dir.exists():
        return 0

    count = 0
    for md_file in sorted(cards_dir.glob("card-*.md")):
        try:
            card = read_card(md_file)
            sync_card_to_index(session, card, project_id, str(md_file))
            count += 1
        except (ValueError, Exception) as e:
            import logging
            logging.warning(f"Skipping {md_file}: {e}")
    return count


def next_card_id(session: Session) -> int:
    """Get next available global card ID from index."""
    result = session.exec(
        select(func.max(CardIndex.card_id))
    ).first()
    return (result or 0) + 1
```

**Step 4: Run tests**

Run: `cd backend && python -m pytest tests/test_card_index.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add backend/app/models/core.py backend/app/core/card_index.py backend/tests/test_card_index.py
git commit -m "feat: card_index.py — SQLite cache index with rebuild and global ID counter"
```

---

## Phase 2: API + Backend Migration (can parallelize after Phase 1)

### Task 4: Rewrite routes.py card endpoints

**Files:**
- Modify: `backend/app/api/routes.py`
- Create: `backend/tests/test_routes_cards.py`

**Summary:** Replace all Card ORM queries with CardIndex queries + card_file read/write. Keep response format identical. Add asyncio.Lock per card. Add `is_system` protection on delete/update for projects and cron jobs.

Key changes:
- `GET /projects/{id}/board` → query CardIndex instead of Card table
- `GET /cards/{id}` → CardIndex lookup + read_card() for full content
- `POST /cards/` → write_card() + sync_card_to_index()
- `PATCH /cards/{id}` → read_card() + modify + write_card() + sync
- `DELETE /cards/{id}` → delete MD file + remove_card_from_index()
- `POST /cards/{id}/trigger` → read + update status + write
- `POST /cards/{id}/abort` → read + update status/content + write
- `DELETE /projects/{id}` → block if is_system
- `DELETE /cron/{id}` → block if is_system
- New: `POST /projects/{id}/reindex`

**Step 1: Write integration tests** (using FastAPI TestClient)

**Step 2: Implement the rewrite**

**Step 3: Run tests, commit**

---

### Task 5: Rewrite poller.py

**Files:**
- Modify: `backend/app/core/poller.py`

**Summary:** Replace Card ORM queries with CardIndex queries. Read MD content when dispatching. Use `update_card()` pattern with asyncio.Lock for all status changes.

Key changes in `_process_pending_cards()`:
- `select(Card).where(Card.status == "pending")` → `query_pending_cards(session)`
- For each pending card: `read_card(file_path)` to get content for AI
- Status changes (pending→running, →idle) use locked write through card_file

Key changes in `_execute_and_update()`:
- Read card from MD, append AI output, write back with lock
- Update CardIndex after write

---

### Task 6: Rewrite cron_poller.py

**Files:**
- Modify: `backend/app/core/cron_poller.py`

**Summary:** When cron job fires, create MD file + sync index instead of Card ORM insert. Tags go into frontmatter. For AEGIS heartbeat/memory cron jobs, inject system metrics into prompt template.

---

### Task 7: Card file watcher

**Files:**
- Create: `backend/app/core/card_watcher.py`
- Modify: `backend/app/main.py` (start watcher in lifespan)

**Summary:** Use watchfiles to monitor all project `.aegis/cards/` directories. On change: compare mtime with CardIndex, if different → read_card + validate + sync_card_to_index + broadcast WebSocket.

---

### Task 8: Migration script

**Files:**
- Create: `backend/migrate_cards_to_md.py`

**Summary:** Read all Cards from DB, write as MD files to each project's `.aegis/cards/`, rebuild CardIndex.

---

## Phase 3: AEGIS System + Memory

### Task 9: AEGIS system project seed + protection

**Files:**
- Modify: `backend/seed.py` (already done in previous commits)
- Modify: `backend/app/api/routes.py` (add is_system guards)

**Summary:** Seed is already written. Add API guards: return 403 on delete/modify of is_system projects and cron jobs.

---

### Task 10: Memory system

**Files:**
- Create: `backend/app/core/memory_manager.py`
- Modify: `backend/app/core/cron_poller.py` (inject memory context into prompts)
- Modify: `backend/app/core/poller.py` (parse memory output format after execution)

**Summary:**
- `memory_manager.py`: read/write short-term and long-term memory MD files
- cron_poller injects `{short_term_memories}`, `{long_term_memories}`, etc. into prompt
- After AI execution, parse `---SHORT_TERM---` / `---LONG_TERM---` delimiters
- Write parsed sections to `memory/short-term/` and `memory/long-term/`
- Cleanup: delete short-term files older than `memory_short_term_days` setting

---

### Task 11: Frontend is_system protection

**Files:**
- Modify: `frontend/src/views/Kanban.vue`
- Modify: `frontend/src/views/CronJobs.vue`

**Summary:** Hide delete buttons and disable rename for `is_system=true` items. API already returns is_system field.

---

### Task 12: Frontend Settings — memory_short_term_days

**Files:**
- Modify: `frontend/src/views/Settings.vue`

**Summary:** Add a number input for `memory_short_term_days` (default 30).

---

### Task 13: Cleanup — remove old Card/CardTagLink

**Files:**
- Modify: `backend/app/models/core.py` (remove Card, CardTagLink classes)
- Modify: all imports referencing Card

**Summary:** After migration is verified, remove the old ORM models. CardIndex is the only card-related table. Keep CardTagLink removal safe by ensuring all tag data is in frontmatter.

---

### Task 14: Startup orphan detection + index rebuild

**Files:**
- Modify: `backend/app/main.py` (lifespan)

**Summary:** On startup, for each active project: `rebuild_index()`. Check for `status=running` entries in CardIndex with no matching `running_tasks` process → reset to `failed`.

---

## Parallelization Map

```
Task 1 (test infra)
  └─→ Task 2 (card_file.py)
       └─→ Task 3 (card_index.py)
            ├─→ Task 4 (routes.py)     ─┐
            ├─→ Task 5 (poller.py)      │── can parallelize
            ├─→ Task 6 (cron_poller.py) │
            └─→ Task 7 (watcher)       ─┘
                 └─→ Task 8 (migration)
                      └─→ Task 13 (cleanup) + Task 14 (startup)

Task 9 (AEGIS seed/protection) ── independent, can start now
  └─→ Task 10 (memory system)

Task 11 (frontend is_system) ── independent, can start after Task 9
Task 12 (frontend settings) ── independent
```
