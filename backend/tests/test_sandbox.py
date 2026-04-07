"""Tests for sandbox module — environment sanitisation and process isolation."""
import os
import platform
import pytest
from unittest.mock import patch, MagicMock
from sqlmodel import Session, SQLModel, create_engine

from app.core.sandbox import build_sanitized_env, get_popen_kwargs, ALLOWED_ENV_KEYS
from app.models.core import ProjectEnvVar


@pytest.fixture
def db_session(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


class TestBuildSanitizedEnv:
    def test_only_whitelisted_keys(self):
        """Only whitelisted env vars should be present."""
        env = build_sanitized_env()
        for key in env:
            assert key in ALLOWED_ENV_KEYS, f"Unexpected key: {key}"

    def test_dangerous_keys_excluded(self):
        """Sensitive keys should NOT leak through."""
        dangerous_keys = [
            "AWS_SECRET_ACCESS_KEY",
            "DATABASE_URL", "SUPABASE_KEY", "OPENAI_API_KEY",
            "CLAUDECODE",
        ]
        with patch.dict(os.environ, {k: "secret" for k in dangerous_keys}):
            env = build_sanitized_env()
            for key in dangerous_keys:
                assert key not in env, f"Leaked: {key}"

    def test_path_is_preserved(self):
        """PATH should always be included."""
        env = build_sanitized_env()
        if "PATH" in os.environ:
            assert "PATH" in env

    def test_claudecode_removed(self):
        """CLAUDECODE should never be in sanitized env."""
        with patch.dict(os.environ, {"CLAUDECODE": "1"}):
            env = build_sanitized_env()
            assert "CLAUDECODE" not in env

    def test_project_env_vars_injected(self, db_session):
        """Project env vars from DB should be injected."""
        # Insert project env vars
        var1 = ProjectEnvVar(project_id=1, key="MY_API_KEY", value="test123", is_secret=True)
        var2 = ProjectEnvVar(project_id=1, key="DEBUG", value="true", is_secret=False)
        db_session.add(var1)
        db_session.add(var2)
        db_session.commit()

        # Patch engine at the import target (app.database.engine used inside sandbox)
        with patch("app.database.engine", db_session.get_bind()):
            env = build_sanitized_env(project_id=1)
            assert env.get("MY_API_KEY") == "test123"
            assert env.get("DEBUG") == "true"

    def test_no_project_id_skips_db(self):
        """Without project_id, no DB query should happen."""
        env = build_sanitized_env(project_id=None)
        assert isinstance(env, dict)

    def test_wrong_project_id_no_vars(self, db_session):
        """Non-existent project_id returns only whitelist vars."""
        var = ProjectEnvVar(project_id=99, key="SHOULD_NOT_APPEAR", value="x")
        db_session.add(var)
        db_session.commit()

        with patch("app.database.engine", db_session.get_bind()):
            env = build_sanitized_env(project_id=1)
            assert "SHOULD_NOT_APPEAR" not in env


class TestGetPopenKwargs:
    def test_returns_dict(self):
        """Should always return a dict."""
        kwargs = get_popen_kwargs()
        assert isinstance(kwargs, dict)

    @patch("app.core.sandbox.platform.system", return_value="Linux")
    def test_linux_start_new_session(self, _mock):
        """Linux should get start_new_session=True."""
        # On Windows, pwd doesn't exist, so the ImportError path will be hit
        # which still results in start_new_session=True
        kwargs = get_popen_kwargs()
        assert kwargs.get("start_new_session") is True

    @patch("app.core.sandbox.platform.system", return_value="Darwin")
    def test_macos_start_new_session(self, _mock):
        """macOS should also get start_new_session=True."""
        kwargs = get_popen_kwargs()
        assert kwargs.get("start_new_session") is True

    def test_windows_creation_flags(self):
        """Windows should get CREATE_NEW_PROCESS_GROUP flags."""
        import subprocess
        with patch("app.core.sandbox.platform.system", return_value="Windows"), \
             patch.object(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200, create=True), \
             patch.object(subprocess, "CREATE_NO_WINDOW", 0x08000000, create=True):
            kwargs = get_popen_kwargs()
            flags = kwargs.get("creationflags", 0)
            assert flags & subprocess.CREATE_NEW_PROCESS_GROUP

    def test_current_platform(self):
        """Should not raise on current platform."""
        kwargs = get_popen_kwargs()
        system = platform.system()
        if system in ("Linux", "Darwin"):
            assert "start_new_session" in kwargs
        elif system == "Windows":
            assert "creationflags" in kwargs


class TestProjectEnvVar:
    def test_model_creation(self, db_session):
        """ProjectEnvVar should be creatable and queryable."""
        var = ProjectEnvVar(
            project_id=1,
            key="TEST_KEY",
            value="test_value",
            is_secret=True,
            description="A test variable",
        )
        db_session.add(var)
        db_session.commit()
        db_session.refresh(var)

        assert var.id is not None
        assert var.key == "TEST_KEY"
        assert var.value == "test_value"
        assert var.is_secret is True

    def test_multiple_vars_per_project(self, db_session):
        """Multiple env vars per project should work."""
        for i in range(5):
            db_session.add(ProjectEnvVar(
                project_id=1, key=f"VAR_{i}", value=f"val_{i}",
            ))
        db_session.commit()

        from sqlmodel import select
        vars = db_session.exec(
            select(ProjectEnvVar).where(ProjectEnvVar.project_id == 1)
        ).all()
        assert len(vars) == 5
