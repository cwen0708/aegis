"""GitSafetyManager 單元測試 — 使用 tmp_path 建立隔離 git repo"""
import git
import pytest

from app.core.git_safety import GitSafetyManager


@pytest.fixture
def tmp_repo(tmp_path):
    """建立臨時 git repo 並提交初始 commit"""
    repo = git.Repo.init(tmp_path)
    repo.config_writer().set_value("user", "name", "Test").release()
    repo.config_writer().set_value("user", "email", "test@test.com").release()
    init_file = tmp_path / "init.txt"
    init_file.write_text("init")
    repo.index.add(["init.txt"])
    repo.index.commit("initial commit")
    return tmp_path


def test_init_valid_repo(tmp_repo):
    mgr = GitSafetyManager(str(tmp_repo))
    assert mgr.repo_path == tmp_repo


def test_init_invalid_path(tmp_path):
    bad_path = tmp_path / "not_a_repo"
    bad_path.mkdir()
    with pytest.raises(ValueError, match="Not a valid git repository"):
        GitSafetyManager(str(bad_path))


def test_is_clean_empty_repo(tmp_repo):
    mgr = GitSafetyManager(str(tmp_repo))
    assert mgr.is_clean() is True


def test_is_clean_with_changes(tmp_repo):
    (tmp_repo / "new_file.txt").write_text("dirty")
    mgr = GitSafetyManager(str(tmp_repo))
    assert mgr.is_clean() is False


def test_stash_changes(tmp_repo):
    (tmp_repo / "work.txt").write_text("wip")
    mgr = GitSafetyManager(str(tmp_repo))
    result = mgr.stash_changes("test stash")
    assert result is True
    assert mgr.is_clean() is True


def test_stash_no_changes(tmp_repo):
    mgr = GitSafetyManager(str(tmp_repo))
    result = mgr.stash_changes()
    assert result is False


def test_commit_changes(tmp_repo):
    (tmp_repo / "feature.txt").write_text("new feature")
    mgr = GitSafetyManager(str(tmp_repo))
    result = mgr.commit_changes("add feature")
    assert result is True
    assert mgr.is_clean() is True
    assert mgr.repo.head.commit.message.strip() == "add feature"


def test_commit_no_changes(tmp_repo):
    mgr = GitSafetyManager(str(tmp_repo))
    result = mgr.commit_changes("nothing")
    assert result is False


def test_create_feature_branch(tmp_repo):
    mgr = GitSafetyManager(str(tmp_repo))
    original = mgr.create_feature_branch("feat/test-branch")
    assert original == "master"
    assert mgr.repo.active_branch.name == "feat/test-branch"


def test_rollback_hard(tmp_repo):
    (tmp_repo / "bad.txt").write_text("bad change")
    mgr = GitSafetyManager(str(tmp_repo))
    assert mgr.is_clean() is False
    mgr.rollback_hard()
    assert mgr.is_clean() is True
    assert not (tmp_repo / "bad.txt").exists()


def test_auto_backup_clean_repo(tmp_repo):
    mgr = GitSafetyManager(str(tmp_repo))
    result = mgr.auto_backup()
    assert result["committed"] is False
    assert result["reason"] == "no changes"


def test_auto_backup_with_changes(tmp_repo):
    (tmp_repo / "backup_test.txt").write_text("some work")
    (tmp_repo / "another.txt").write_text("more work")
    mgr = GitSafetyManager(str(tmp_repo))
    result = mgr.auto_backup()
    assert result["committed"] is True
    assert result["files_changed"] == 2
    assert result["sha"] and len(result["sha"]) == 8
    assert "backup: auto-save" in result["message"]
    # repo 應該是乾淨的
    assert mgr.is_clean() is True
