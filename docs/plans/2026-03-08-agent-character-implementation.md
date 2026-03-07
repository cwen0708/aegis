# Agent Character Personalization — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Give each AI team member a persistent identity (soul), skills, and memory, with task dispatch creating temp workspaces that leverage CLI native config reading.

**Architecture:** Member profiles live at `~/.aegis/members/{slug}/` with `soul.md`, `skills/`, `memory/`. On task dispatch, a temp workspace is created at `~/.aegis/workspaces/task-{card_id}/` containing a provider-specific config file (`CLAUDE.md` or `.gemini.md`) and skills directory (`.claude/skills/` or `.gemini/skills/`). After task completion, the workspace is destroyed and a short-term memory entry is written.

**Tech Stack:** Python 3, FastAPI, SQLModel, pathlib, shutil

**Design doc:** `docs/plans/2026-03-07-agent-character-personalization-design.md`

---

### Task 1: Add `slug` field to Member model

**Files:**
- Modify: `backend/app/models/core.py:114-124`
- Test: `backend/tests/test_member_profile.py` (created in Task 2)

**Step 1: Add slug field to Member**

In `backend/app/models/core.py`, add `slug` to the `Member` class:

```python
class Member(SQLModel, table=True):
    """AI 團隊成員（虛擬角色）"""
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str  # "財務小陳"
    slug: str = ""  # 資料夾名稱，如 "xiao-jun"
    avatar: str = ""  # emoji
    role: str = ""  # "資深開發者"
    description: str = ""
    sprite_index: int = Field(default=0)  # 小人物圖索引 0-5
    portrait: str = ""  # 立繪圖片路徑
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

**Step 2: Commit**

```bash
git add backend/app/models/core.py
git commit -m "feat: add slug field to Member model"
```

---

### Task 2: Create `member_profile.py` with tests

**Files:**
- Create: `backend/app/core/member_profile.py`
- Create: `backend/tests/test_member_profile.py`

**Step 1: Write the failing tests**

Create `backend/tests/test_member_profile.py`:

```python
import pytest
from pathlib import Path
from app.core.member_profile import (
    get_member_dir,
    get_soul_content,
    get_skills_dir,
    get_member_memory_dir,
    MEMBERS_ROOT,
)


@pytest.fixture
def member_dir(tmp_path, monkeypatch):
    """Patch MEMBERS_ROOT to use tmp_path"""
    monkeypatch.setattr("app.core.member_profile.MEMBERS_ROOT", tmp_path)
    slug = "test-member"
    d = tmp_path / slug
    d.mkdir()
    return d, slug


def test_get_member_dir(member_dir):
    d, slug = member_dir
    result = get_member_dir(slug)
    assert result == d
    assert result.exists()


def test_get_member_dir_creates_if_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("app.core.member_profile.MEMBERS_ROOT", tmp_path)
    result = get_member_dir("new-member")
    assert result.exists()
    assert (result / "skills").exists()
    assert (result / "memory" / "short-term").exists()
    assert (result / "memory" / "long-term").exists()


def test_get_soul_content(member_dir):
    d, slug = member_dir
    soul_text = "# Test Soul\n\nYou are a test agent."
    (d / "soul.md").write_text(soul_text, encoding="utf-8")
    assert get_soul_content(slug) == soul_text


def test_get_soul_content_missing(member_dir):
    _, slug = member_dir
    assert get_soul_content(slug) == ""


def test_get_skills_dir(member_dir):
    d, slug = member_dir
    skills = d / "skills"
    skills.mkdir()
    (skills / "python.md").write_text("# Python", encoding="utf-8")
    result = get_skills_dir(slug)
    assert result == skills
    assert list(result.glob("*.md")) != []


def test_get_member_memory_dir(member_dir):
    d, slug = member_dir
    mem = get_member_memory_dir(slug)
    assert mem == d / "memory"
    assert (mem / "short-term").exists()
    assert (mem / "long-term").exists()
```

**Step 2: Run tests to verify they fail**

```bash
cd backend && python -m pytest tests/test_member_profile.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'app.core.member_profile'`

**Step 3: Write the implementation**

Create `backend/app/core/member_profile.py`:

```python
"""Member profile management — soul, skills, memory directories."""
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

MEMBERS_ROOT = Path.home() / ".aegis" / "members"


def get_member_dir(slug: str) -> Path:
    """Return (and ensure) the member's profile directory."""
    d = MEMBERS_ROOT / slug
    d.mkdir(parents=True, exist_ok=True)
    (d / "skills").mkdir(exist_ok=True)
    (d / "memory" / "short-term").mkdir(parents=True, exist_ok=True)
    (d / "memory" / "long-term").mkdir(parents=True, exist_ok=True)
    return d


def get_soul_content(slug: str) -> str:
    """Read soul.md content for a member. Returns empty string if missing."""
    soul_file = get_member_dir(slug) / "soul.md"
    if soul_file.exists():
        return soul_file.read_text(encoding="utf-8")
    return ""


def get_skills_dir(slug: str) -> Path:
    """Return the member's skills directory."""
    return get_member_dir(slug) / "skills"


def get_member_memory_dir(slug: str) -> Path:
    """Return (and ensure) the member's memory directory."""
    d = get_member_dir(slug) / "memory"
    (d / "short-term").mkdir(parents=True, exist_ok=True)
    (d / "long-term").mkdir(parents=True, exist_ok=True)
    return d
```

**Step 4: Run tests to verify they pass**

```bash
cd backend && python -m pytest tests/test_member_profile.py -v
```

Expected: All 6 tests PASS

**Step 5: Commit**

```bash
git add backend/app/core/member_profile.py backend/tests/test_member_profile.py
git commit -m "feat: member_profile.py — soul, skills, memory directory management"
```

---

### Task 3: Create `task_workspace.py` with tests

**Files:**
- Create: `backend/app/core/task_workspace.py`
- Create: `backend/tests/test_task_workspace.py`

**Step 1: Write the failing tests**

Create `backend/tests/test_task_workspace.py`:

```python
import pytest
from pathlib import Path
from app.core.task_workspace import (
    prepare_workspace,
    cleanup_workspace,
    WORKSPACES_ROOT,
    PROVIDER_CONFIG,
)


@pytest.fixture
def ws_root(tmp_path, monkeypatch):
    """Patch WORKSPACES_ROOT and MEMBERS_ROOT to tmp dirs"""
    monkeypatch.setattr("app.core.task_workspace.WORKSPACES_ROOT", tmp_path / "workspaces")
    monkeypatch.setattr("app.core.member_profile.MEMBERS_ROOT", tmp_path / "members")
    return tmp_path


def _setup_member(ws_root, slug="test-dev"):
    """Helper: create a member profile with soul + skills"""
    member_dir = ws_root / "members" / slug
    member_dir.mkdir(parents=True)
    (member_dir / "soul.md").write_text("# Test Dev\nYou are a test developer.", encoding="utf-8")
    skills_dir = member_dir / "skills"
    skills_dir.mkdir()
    (skills_dir / "python.md").write_text("# Python best practices", encoding="utf-8")
    (skills_dir / "testing.md").write_text("# Testing guidelines", encoding="utf-8")
    mem_dir = member_dir / "memory"
    (mem_dir / "short-term").mkdir(parents=True)
    (mem_dir / "long-term").mkdir(parents=True)
    return slug


def test_prepare_workspace_claude(ws_root):
    slug = _setup_member(ws_root)
    ws = prepare_workspace(
        card_id=42,
        member_slug=slug,
        provider="claude",
        project_path="/fake/project",
        card_content="## Task\nDo something",
    )
    assert ws.exists()
    # CLAUDE.md should exist
    claude_md = ws / "CLAUDE.md"
    assert claude_md.exists()
    content = claude_md.read_text(encoding="utf-8")
    assert "/fake/project" in content
    assert "Test Dev" in content
    assert "Do something" in content
    assert "memory" in content
    # skills copied
    skills_dir = ws / ".claude" / "skills"
    assert skills_dir.exists()
    assert (skills_dir / "python.md").exists()
    assert (skills_dir / "testing.md").exists()


def test_prepare_workspace_gemini(ws_root):
    slug = _setup_member(ws_root)
    ws = prepare_workspace(
        card_id=99,
        member_slug=slug,
        provider="gemini",
        project_path="/fake/project",
        card_content="## Task\nGemini task",
    )
    # .gemini.md should exist (not CLAUDE.md)
    assert (ws / ".gemini.md").exists()
    assert not (ws / "CLAUDE.md").exists()
    # skills in .gemini/skills/
    assert (ws / ".gemini" / "skills" / "python.md").exists()


def test_cleanup_workspace(ws_root):
    slug = _setup_member(ws_root)
    ws = prepare_workspace(
        card_id=7, member_slug=slug, provider="claude",
        project_path="/x", card_content="test",
    )
    assert ws.exists()
    cleanup_workspace(7)
    assert not ws.exists()


def test_cleanup_workspace_nonexistent(ws_root):
    """Should not raise even if workspace doesn't exist"""
    cleanup_workspace(999)


def test_prepare_workspace_no_skills(ws_root):
    """Member with soul but no skills should still work"""
    slug = "no-skills"
    member_dir = ws_root / "members" / slug
    member_dir.mkdir(parents=True)
    (member_dir / "soul.md").write_text("# Solo\nNo skills.", encoding="utf-8")
    (member_dir / "skills").mkdir()
    (member_dir / "memory" / "short-term").mkdir(parents=True)
    (member_dir / "memory" / "long-term").mkdir(parents=True)
    ws = prepare_workspace(
        card_id=1, member_slug=slug, provider="claude",
        project_path="/x", card_content="test",
    )
    assert (ws / "CLAUDE.md").exists()
    assert (ws / ".claude" / "skills").exists()
```

**Step 2: Run tests to verify they fail**

```bash
cd backend && python -m pytest tests/test_task_workspace.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'app.core.task_workspace'`

**Step 3: Write the implementation**

Create `backend/app/core/task_workspace.py`:

```python
"""Task workspace management — create/cleanup temp dirs for AI task execution."""
import logging
import shutil
from pathlib import Path

from app.core.member_profile import get_member_dir, get_soul_content, get_skills_dir, get_member_memory_dir

logger = logging.getLogger(__name__)

WORKSPACES_ROOT = Path.home() / ".aegis" / "workspaces"

# Provider-specific file/dir names
PROVIDER_CONFIG = {
    "claude": {"config_file": "CLAUDE.md", "dot_dir": ".claude"},
    "gemini": {"config_file": ".gemini.md", "dot_dir": ".gemini"},
}


def _build_config_content(
    soul_content: str,
    member_slug: str,
    project_path: str,
    card_content: str,
) -> str:
    """Assemble the CLAUDE.md / .gemini.md content."""
    memory_path = get_member_memory_dir(member_slug)
    return f"""# 工作目錄
你的專案在 {project_path}
所有程式碼修改都在那個目錄進行。

# 你的身份
{soul_content}

# 記憶
你的個人記憶存放在：
{memory_path}
- short-term/ 短期記憶（近期任務摘要）
- long-term/ 長期記憶（累積的經驗與模式）
需要回憶時可以去讀取。

# 本次任務
{card_content}
"""


def prepare_workspace(
    card_id: int,
    member_slug: str,
    provider: str,
    project_path: str,
    card_content: str,
) -> Path:
    """
    Create a temp workspace directory for the AI task.
    Returns the workspace path.
    """
    cfg = PROVIDER_CONFIG.get(provider, PROVIDER_CONFIG["claude"])
    ws = WORKSPACES_ROOT / f"task-{card_id}"
    ws.mkdir(parents=True, exist_ok=True)

    # 1. Build and write config file (CLAUDE.md or .gemini.md)
    soul = get_soul_content(member_slug)
    content = _build_config_content(soul, member_slug, project_path, card_content)
    (ws / cfg["config_file"]).write_text(content, encoding="utf-8")

    # 2. Copy skills into .claude/skills/ or .gemini/skills/
    dot_dir = ws / cfg["dot_dir"]
    target_skills = dot_dir / "skills"
    target_skills.mkdir(parents=True, exist_ok=True)

    src_skills = get_skills_dir(member_slug)
    if src_skills.exists():
        for md_file in src_skills.glob("*.md"):
            shutil.copy2(md_file, target_skills / md_file.name)

    logger.info(f"[Workspace] Created task-{card_id} for {member_slug} ({provider})")
    return ws


def cleanup_workspace(card_id: int) -> None:
    """Remove the temp workspace directory."""
    ws = WORKSPACES_ROOT / f"task-{card_id}"
    if ws.exists():
        shutil.rmtree(ws, ignore_errors=True)
        logger.info(f"[Workspace] Cleaned up task-{card_id}")
```

**Step 4: Run tests to verify they pass**

```bash
cd backend && python -m pytest tests/test_task_workspace.py -v
```

Expected: All 5 tests PASS

**Step 5: Commit**

```bash
git add backend/app/core/task_workspace.py backend/tests/test_task_workspace.py
git commit -m "feat: task_workspace.py — temp workspace create/cleanup for AI tasks"
```

---

### Task 4: Add member memory functions to `memory_manager.py`

**Files:**
- Modify: `backend/app/core/memory_manager.py`
- Create: `backend/tests/test_member_memory.py`

**Step 1: Write the failing tests**

Create `backend/tests/test_member_memory.py`:

```python
import pytest
from pathlib import Path
from app.core.memory_manager import (
    write_member_short_term_memory,
    read_member_short_term_memories,
    cleanup_member_short_term,
)


@pytest.fixture
def member_mem(tmp_path, monkeypatch):
    """Patch MEMBERS_ROOT so memory writes go to tmp_path"""
    monkeypatch.setattr("app.core.member_profile.MEMBERS_ROOT", tmp_path)
    slug = "test-dev"
    mem = tmp_path / slug / "memory"
    (mem / "short-term").mkdir(parents=True)
    (mem / "long-term").mkdir(parents=True)
    return slug


def test_write_member_short_term(member_mem):
    path = write_member_short_term_memory(member_mem, "Task completed successfully")
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "Task completed successfully" in content
    assert path.parent.name == "short-term"


def test_read_member_short_term(member_mem):
    write_member_short_term_memory(member_mem, "Memory entry 1")
    result = read_member_short_term_memories(member_mem, days=7)
    assert "Memory entry 1" in result


def test_read_member_short_term_empty(member_mem):
    result = read_member_short_term_memories(member_mem, days=7)
    assert "no recent" in result
```

**Step 2: Run tests to verify they fail**

```bash
cd backend && python -m pytest tests/test_member_memory.py -v
```

Expected: FAIL — `ImportError: cannot import name 'write_member_short_term_memory'`

**Step 3: Add member memory functions to memory_manager.py**

Append to `backend/app/core/memory_manager.py`:

```python
# ── Member-level memory (delegates to member_profile for paths) ──

def _get_member_short_term_dir(member_slug: str) -> Path:
    from app.core.member_profile import get_member_memory_dir
    d = get_member_memory_dir(member_slug) / "short-term"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _get_member_long_term_dir(member_slug: str) -> Path:
    from app.core.member_profile import get_member_memory_dir
    d = get_member_memory_dir(member_slug) / "long-term"
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_member_short_term_memory(member_slug: str, content: str, timestamp: datetime = None) -> Path:
    """Write a short-term memory file for a specific member."""
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)
    filename = timestamp.strftime("%Y-%m-%d-%H%M") + ".md"
    fpath = _get_member_short_term_dir(member_slug) / filename

    frontmatter = f"""---
timestamp: "{timestamp.isoformat()}"
member: "{member_slug}"
---

"""
    fpath.write_text(frontmatter + content, encoding="utf-8")
    logger.info(f"Member short-term memory written: {fpath}")
    return fpath


def read_member_short_term_memories(member_slug: str, days: int = 7) -> str:
    """Read all short-term memories for a member from the last N days."""
    d = _get_member_short_term_dir(member_slug)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    entries = []

    for f in sorted(d.glob("*.md")):
        try:
            date_str = f.stem
            file_date = datetime.strptime(date_str, "%Y-%m-%d-%H%M").replace(tzinfo=timezone.utc)
            if file_date >= cutoff:
                entries.append(f"### {date_str}\n\n{f.read_text(encoding='utf-8')}")
        except (ValueError, OSError) as e:
            logger.warning(f"Skipping {f}: {e}")

    return "\n\n---\n\n".join(entries) if entries else "(no recent short-term memories)"


def cleanup_member_short_term(member_slug: str, retention_days: int = 30) -> int:
    """Delete member short-term memory files older than retention_days."""
    d = _get_member_short_term_dir(member_slug)
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    deleted = 0

    for f in d.glob("*.md"):
        try:
            date_str = f.stem
            file_date = datetime.strptime(date_str, "%Y-%m-%d-%H%M").replace(tzinfo=timezone.utc)
            if file_date < cutoff:
                f.unlink()
                deleted += 1
        except (ValueError, OSError):
            pass

    return deleted
```

**Step 4: Run tests to verify they pass**

```bash
cd backend && python -m pytest tests/test_member_memory.py -v
```

Expected: All 3 tests PASS

**Step 5: Commit**

```bash
git add backend/app/core/memory_manager.py backend/tests/test_member_memory.py
git commit -m "feat: add member-level short-term memory to memory_manager"
```

---

### Task 5: Integrate workspace into `poller.py`

**Files:**
- Modify: `backend/app/core/poller.py:71-97` (dispatch section)
- Modify: `backend/app/core/poller.py:146-189` (`_execute_and_update`)

**Step 1: Add workspace creation in dispatch**

In `poller.py`, import the new modules at the top:

```python
from app.core.task_workspace import prepare_workspace, cleanup_workspace
from app.core.memory_manager import write_member_short_term_memory
```

In `_process_pending_cards()`, after the member resolve block (line ~90), before `asyncio.create_task`, add workspace preparation. Change the `create_task` call to pass `workspace_dir` and `member_slug`:

```python
                project_name = project.name if project else "Unknown"
                card_title = idx.title

                # 建立臨時工作區（有指派角色時）
                workspace_dir = None
                member_slug = None
                if member_id:
                    from app.models.core import Member as MemberModel
                    member_obj = session.get(MemberModel, member_id)
                    if member_obj and member_obj.slug:
                        member_slug = member_obj.slug
                        workspace_dir = str(prepare_workspace(
                            card_id=idx.card_id,
                            member_slug=member_slug,
                            provider=forced_provider or "claude",
                            project_path=project_path,
                            card_content=card_data.content,
                        ))

                asyncio.create_task(_execute_and_update(
                    idx.card_id, project_path, card_data.content, phase,
                    card_title, project_name, forced_provider, member_id,
                    idx.project_id, str(idx.file_path),
                    workspace_dir=workspace_dir, member_slug=member_slug,
                ))
```

**Step 2: Update `_execute_and_update` signature and add cleanup + memory write**

```python
async def _execute_and_update(
    card_id: int, project_path: str, prompt: str, phase: str,
    card_title: str = "", project_name: str = "",
    forced_provider: str | None = None, member_id: int | None = None,
    project_id: int = 0, file_path_str: str = "",
    workspace_dir: str | None = None, member_slug: str | None = None,
):
    """包裝 run_ai_task，並在完成後更新 MD 檔案與資料庫卡片狀態"""
    # 有工作區時，cwd 用工作區；prompt 簡化為指示讀取 config
    effective_cwd = workspace_dir or project_path
    effective_prompt = "請閱讀你的設定檔並執行本次任務。" if workspace_dir else prompt

    result = await run_ai_task(
        card_id, effective_cwd, effective_prompt, phase,
        forced_provider=forced_provider, card_title=card_title,
        project_name=project_name, member_id=member_id,
    )

    async with get_card_lock(card_id):
        # ... (existing card status update logic unchanged) ...
        pass

    # 寫入角色短期記憶
    if member_slug:
        try:
            status_text = result.get("status", "unknown")
            output_preview = result.get("output", "")[:500]
            write_member_short_term_memory(
                member_slug,
                f"## 任務: {card_title}\n專案: {project_name}\n結果: {status_text}\n\n{output_preview}"
            )
        except Exception as e:
            logger.warning(f"[Memory] Failed to write member memory: {e}")

    # 清理臨時工作區
    if workspace_dir:
        cleanup_workspace(card_id)
```

**Step 3: Commit**

```bash
git add backend/app/core/poller.py
git commit -m "feat: integrate task workspace + member memory into poller dispatch"
```

---

### Task 6: Update `runner.py` to accept workspace cwd

**Files:**
- Modify: `backend/app/core/runner.py:110-139`

**Step 1: No structural change needed**

`run_ai_task` already accepts `project_path` as cwd — poller now passes `workspace_dir` instead when available. The only change is that when a workspace is used, the prompt should be shorter (poller handles this).

Verify the existing `run_ai_task` signature works by reading the code — `project_path` parameter is used directly as `cwd` at line 139. No code change needed in runner.py.

**Step 2: Commit (skip if no changes)**

No commit needed for this task.

---

### Task 7: Update `seed.py` to create member profiles

**Files:**
- Modify: `backend/seed.py`

**Step 1: Update member creation with slugs and profile dirs**

Add to `seed.py` imports:

```python
from app.core.member_profile import get_member_dir
```

Update the member creation section:

```python
        # ── 2. Members (AI 虛擬角色，範例) ──
        m1 = Member(
            name="小筃",
            slug="xiao-jun",
            avatar="👩‍💻",
            role="資深開發者",
            description="擅長全端開發與系統架構，負責 Coding 階段的任務執行。",
            sprite_index=0,
            portrait="/api/v1/portraits/example_1.png",
        )
        m2 = Member(
            name="小良",
            slug="xiao-liang",
            avatar="👨‍💼",
            role="技術主管",
            description="負責 Planning 與 Code Review，擅長需求分析與技術決策。",
            sprite_index=1,
            portrait="/api/v1/portraits/example_2.png",
        )
        session.add_all([m1, m2])
        session.commit()
        session.refresh(m1)
        session.refresh(m2)

        # ── 2b. Member Profile Directories ──
        _seed_member_profiles()
```

Add the `_seed_member_profiles` function:

```python
def _seed_member_profiles():
    """Create member profile directories with initial soul.md and skills."""
    # 小筃 — 資深開發者
    jun_dir = get_member_dir("xiao-jun")
    (jun_dir / "soul.md").write_text(
        "# 小筃 — 資深開發者\n\n"
        "## 身份\n"
        "你是 Aegis AI 開發團隊的資深全端工程師「小筃」。\n\n"
        "## 專長\n"
        "- Vue 3 Composition API + TypeScript\n"
        "- Python FastAPI 後端\n"
        "- 系統架構設計\n\n"
        "## 工作風格\n"
        "- 先讀現有程式碼再動手\n"
        "- 小步提交、單一責任\n"
        "- 繁體中文註解與 commit message\n"
        "- 不自作主張加功能\n",
        encoding="utf-8",
    )
    (jun_dir / "skills" / "fullstack-dev.md").write_text(
        "# 全端開發規範\n\n"
        "- 前端使用 Vue 3 Composition API + <script setup>\n"
        "- 後端使用 FastAPI + SQLModel\n"
        "- API 路由放在 app/api/routes.py\n"
        "- 新功能要加測試\n",
        encoding="utf-8",
    )

    # 小良 — 技術主管
    liang_dir = get_member_dir("xiao-liang")
    (liang_dir / "soul.md").write_text(
        "# 小良 — 技術主管\n\n"
        "## 身份\n"
        "你是 Aegis AI 開發團隊的技術主管「小良」。\n\n"
        "## 專長\n"
        "- 需求分析與技術決策\n"
        "- Code Review\n"
        "- 架構規劃\n\n"
        "## 工作風格\n"
        "- 注重全局觀，先看整體再看細節\n"
        "- Review 時指出問題但也肯定優點\n"
        "- 決策要附帶理由\n",
        encoding="utf-8",
    )
    (liang_dir / "skills" / "code-review.md").write_text(
        "# Code Review 規範\n\n"
        "- 檢查安全性（OWASP Top 10）\n"
        "- 檢查效能瓶頸\n"
        "- 確認測試覆蓋率\n"
        "- 風格一致性\n",
        encoding="utf-8",
    )
```

**Step 2: Commit**

```bash
git add backend/seed.py
git commit -m "feat: seed member profiles with soul.md and skills"
```

---

### Task 8: Run full test suite and fix any issues

**Files:**
- All test files

**Step 1: Run all tests**

```bash
cd backend && python -m pytest tests/ -v
```

Expected: All tests PASS (existing + new)

**Step 2: Fix any failures if needed**

**Step 3: Commit any fixes**

```bash
git commit -am "fix: address test failures from character personalization"
```

---

### Task 9: Final integration commit

**Step 1: Run full test suite one more time**

```bash
cd backend && python -m pytest tests/ -v
```

**Step 2: Review all changes**

```bash
git log --oneline -10
git diff main --stat
```

---

## Summary of deliverables

| Task | Module | Tests |
|------|--------|-------|
| 1 | Member.slug field | (covered by Task 2) |
| 2 | member_profile.py | test_member_profile.py (6 tests) |
| 3 | task_workspace.py | test_task_workspace.py (5 tests) |
| 4 | memory_manager.py additions | test_member_memory.py (3 tests) |
| 5 | poller.py integration | (integration, existing tests) |
| 6 | runner.py (no change needed) | — |
| 7 | seed.py profiles | — |
| 8-9 | Full test suite + review | — |

**Total new tests: 14**
**New files: 4** (member_profile.py, task_workspace.py, test_member_profile.py, test_task_workspace.py, test_member_memory.py)
**Modified files: 4** (core.py, memory_manager.py, poller.py, seed.py)
