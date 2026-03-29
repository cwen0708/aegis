"""SkillGeneratorHook 測試 — 信心分數計算與 skill 模板生成"""
import pytest
import tempfile
import os
from unittest.mock import patch, MagicMock
from app.hooks import TaskContext
from app.hooks.skill_generator import SkillGeneratorHook


class TestCalculateConfidence:
    """信心分數計算測試"""

    def test_full_score_perfect_execution(self):
        """完美執行應該獲得 1.0 分"""
        hook = SkillGeneratorHook()
        ctx = TaskContext(
            status="completed",
            exit_code=0,
            output="A" * 150,  # > 100 字
        )
        score = hook._calculate_confidence(ctx)
        assert score == pytest.approx(1.0, abs=1e-9)

    def test_zero_score_failed_status(self):
        """失敗狀態應該是 0.0 分"""
        hook = SkillGeneratorHook()
        ctx = TaskContext(
            status="failed",
            exit_code=1,
            output="Error occurred",
        )
        # on_complete 中會在 status != "completed" 時設置 confidence_score = 0.0
        assert ctx.status != "completed"

    def test_failed_exit_code_with_good_output(self):
        """exit_code 非 0，但無其他問題，應該獲得 0.5 分 (output: +0.2, no timeout: +0.2, no error: +0.1)"""
        hook = SkillGeneratorHook()
        ctx = TaskContext(
            status="completed",
            exit_code=1,  # 失敗
            output="A" * 150,  # > 100 字
        )
        score = hook._calculate_confidence(ctx)
        # exit_code != 0: +0, output > 100: +0.2, no timeout: +0.2, no error keywords: +0.1 = 0.5
        assert score == pytest.approx(0.5, abs=1e-9)

    def test_no_output_penalty(self):
        """輸出過短 (<= 100 字)，應該扣分"""
        hook = SkillGeneratorHook()
        ctx = TaskContext(
            status="completed",
            exit_code=0,
            output="Short output",  # < 100 字
        )
        score = hook._calculate_confidence(ctx)
        # exit_code == 0: +0.5, output <= 100: +0, no timeout: +0.2, no error: +0.1 = 0.8
        assert score == pytest.approx(0.8, abs=1e-9)

    def test_timeout_detection(self):
        """檢測超時關鍵字應該扣分"""
        hook = SkillGeneratorHook()
        ctx = TaskContext(
            status="completed",
            exit_code=0,
            output="A" * 150 + " timeout occurred",
        )
        score = hook._calculate_confidence(ctx)
        # exit_code == 0: +0.5, output > 100: +0.2, timeout detected: +0, no error: +0.1 = 0.8
        assert score == pytest.approx(0.8, abs=1e-9)

    def test_timed_out_detection(self):
        """檢測 timed out 關鍵字"""
        hook = SkillGeneratorHook()
        ctx = TaskContext(
            status="completed",
            exit_code=0,
            output="A" * 150 + " timed out",
        )
        score = hook._calculate_confidence(ctx)
        assert score == pytest.approx(0.8, abs=1e-9)

    def test_error_keyword_detection(self):
        """檢測 error 關鍵字應該扣分"""
        hook = SkillGeneratorHook()
        ctx = TaskContext(
            status="completed",
            exit_code=0,
            output="A" * 150 + " Error detected",
        )
        score = hook._calculate_confidence(ctx)
        # exit_code == 0: +0.5, output > 100: +0.2, no timeout: +0.2, error keyword: +0 = 0.9
        assert score == pytest.approx(0.9, abs=1e-9)

    def test_exception_keyword_detection(self):
        """檢測 exception 關鍵字"""
        hook = SkillGeneratorHook()
        ctx = TaskContext(
            status="completed",
            exit_code=0,
            output="A" * 150 + " exception raised",
        )
        score = hook._calculate_confidence(ctx)
        assert score == pytest.approx(0.9, abs=1e-9)

    def test_traceback_keyword_detection(self):
        """檢測 traceback 關鍵字"""
        hook = SkillGeneratorHook()
        ctx = TaskContext(
            status="completed",
            exit_code=0,
            output="A" * 150 + " Traceback:",
        )
        score = hook._calculate_confidence(ctx)
        assert score == pytest.approx(0.9, abs=1e-9)

    def test_failed_keyword_detection(self):
        """檢測 failed 關鍵字"""
        hook = SkillGeneratorHook()
        ctx = TaskContext(
            status="completed",
            exit_code=0,
            output="A" * 150 + " test failed",
        )
        score = hook._calculate_confidence(ctx)
        assert score == pytest.approx(0.9, abs=1e-9)

    def test_score_bounds(self):
        """信心分數應該在 0.0-1.0 範圍內"""
        hook = SkillGeneratorHook()
        # 建立各種邊界情況的 context
        test_cases = [
            TaskContext(status="completed", exit_code=0, output=""),
            TaskContext(status="completed", exit_code=0, output="A" * 1000),
            TaskContext(status="completed", exit_code=1, output="Error: Failed"),
            TaskContext(status="completed", exit_code=-1, output="timeout"),
        ]
        for ctx in test_cases:
            score = hook._calculate_confidence(ctx)
            assert 0.0 <= score <= 1.0, f"Score {score} out of bounds for context {ctx}"

    def test_case_insensitive_keyword_detection(self):
        """關鍵字檢測應該不區分大小寫"""
        hook = SkillGeneratorHook()
        ctx1 = TaskContext(
            status="completed",
            exit_code=0,
            output="A" * 150 + " TIMEOUT DETECTED",
        )
        ctx2 = TaskContext(
            status="completed",
            exit_code=0,
            output="A" * 150 + " timeout detected",
        )
        assert hook._calculate_confidence(ctx1) == pytest.approx(hook._calculate_confidence(ctx2), abs=1e-9)


class TestSkillTemplateGeneration:
    """Skill 模板生成測試"""

    def test_template_includes_confidence_score_in_frontmatter(self):
        """模板的 frontmatter 應該包含 confidence_score"""
        hook = SkillGeneratorHook()
        ctx = TaskContext(
            card_id=123,
            card_title="Test Skill",
            project_name="test-project",
            status="completed",
            exit_code=0,
            output="A" * 150,
            confidence_score=0.95,
        )
        template = hook._build_skill_template(ctx, ["file1.py"], ["def test()"])
        assert "confidence_score: 0.95" in template

    def test_template_shows_confidence_percentage(self):
        """模板應該顯示信心分數百分比"""
        hook = SkillGeneratorHook()
        ctx = TaskContext(
            card_id=123,
            card_title="Test Skill",
            project_name="test-project",
            status="completed",
            exit_code=0,
            output="A" * 150,
            confidence_score=0.75,
        )
        template = hook._build_skill_template(ctx, [], [])
        assert "75%" in template
        assert "0.75/1.0" in template

    def test_template_has_confidence_note(self):
        """模板應該包含信心分數說明"""
        hook = SkillGeneratorHook()
        ctx = TaskContext(
            card_id=123,
            card_title="Test Skill",
            project_name="test-project",
            status="completed",
            exit_code=0,
            output="A" * 150,
            confidence_score=1.0,
        )
        template = hook._build_skill_template(ctx, [], [])
        assert "此 skill 的信心分數為" in template
        assert "評估該 pattern 的可靠性" in template

    def test_template_structure(self):
        """模板應該包含所有必要的部分"""
        hook = SkillGeneratorHook()
        ctx = TaskContext(
            card_id=123,
            card_title="Test Skill",
            project_name="test-project",
            status="completed",
            exit_code=0,
            output="A" * 150,
        )
        template = hook._build_skill_template(ctx, ["file1.py"], ["def test()"])
        assert "---" in template
        assert "name: Test Skill" in template
        assert "generated_from_card: 123" in template
        assert "project: test-project" in template
        assert "## 修改的檔案" in template
        assert "## 新增的函式 / 方法" in template
        assert "## 使用說明" in template
        assert "## 注意事項" in template


class TestSaveSkillPaths:
    """_save_skill 路徑測試"""

    def test_saves_to_drafts_when_member_slug_given(self, tmp_path, monkeypatch):
        """有 member_slug 時，應寫入 skills/drafts/"""
        monkeypatch.setattr("app.core.member_profile.MEMBERS_ROOT", tmp_path)
        # 建立 member dir（含 drafts/active）
        from app.core.member_profile import get_member_dir
        get_member_dir("test-member")

        hook = SkillGeneratorHook()
        hook._save_skill("test-member", "# Test Content")

        drafts_dir = tmp_path / "test-member" / "skills" / "drafts"
        files = list(drafts_dir.glob("*.md"))
        assert len(files) == 1
        assert files[0].read_text(encoding="utf-8") == "# Test Content"

    def test_saves_to_legacy_path_when_no_slug(self, tmp_path):
        """無 member_slug 時，應 fallback 到 .claude/skills/"""
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        hook = SkillGeneratorHook()
        hook._save_skill("", "# Legacy Content", str(project_dir))

        legacy_dir = project_dir / ".claude" / "skills"
        files = list(legacy_dir.glob("*.md"))
        assert len(files) == 1
        assert files[0].read_text(encoding="utf-8") == "# Legacy Content"

    def test_on_complete_passes_member_slug_to_save(self, monkeypatch, tmp_path):
        """on_complete 應傳 member_slug 給 _save_skill"""
        monkeypatch.setattr("app.core.member_profile.MEMBERS_ROOT", tmp_path)
        from app.core.member_profile import get_member_dir
        get_member_dir("slug-member")

        calls = []
        original_save = SkillGeneratorHook._save_skill

        def fake_save(self, member_slug, content, project_path=""):
            calls.append(member_slug)

        import unittest.mock as mock
        with mock.patch.object(SkillGeneratorHook, "_get_git_diff", return_value="diff --git a/f b/f\n+code"):
            with mock.patch.object(SkillGeneratorHook, "_save_skill", fake_save):
                hook = SkillGeneratorHook()
                ctx = TaskContext(
                    status="completed",
                    project_path=str(tmp_path),
                    member_slug="slug-member",
                    output="A" * 150,
                    exit_code=0,
                )
                hook.on_complete(ctx)

        assert calls == ["slug-member"]


class TestOnCompleteIntegration:
    """on_complete 整合測試"""

    @patch.object(SkillGeneratorHook, "_get_git_diff")
    @patch.object(SkillGeneratorHook, "_save_skill")
    def test_failed_status_sets_zero_confidence(self, mock_save, mock_diff):
        """失敗狀態應該設置 confidence_score = 0.0"""
        hook = SkillGeneratorHook()
        ctx = TaskContext(
            status="failed",
            output="Task failed",
            exit_code=1,
        )
        hook.on_complete(ctx)
        assert ctx.confidence_score == 0.0
        mock_save.assert_not_called()  # 不應該生成 skill

    @patch.object(SkillGeneratorHook, "_get_git_diff")
    @patch.object(SkillGeneratorHook, "_save_skill")
    def test_no_diff_skips_skill_generation(self, mock_save, mock_diff):
        """沒有 diff 時應該跳過生成"""
        mock_diff.return_value = ""
        hook = SkillGeneratorHook()
        ctx = TaskContext(
            status="completed",
            project_path="/tmp",
            output="A" * 150,
            exit_code=0,
        )
        hook.on_complete(ctx)
        mock_save.assert_not_called()

    @patch.object(SkillGeneratorHook, "_get_git_diff")
    @patch.object(SkillGeneratorHook, "_extract_changed_files")
    @patch.object(SkillGeneratorHook, "_extract_new_functions")
    @patch.object(SkillGeneratorHook, "_save_skill")
    def test_complete_flow(self, mock_save, mock_funcs, mock_files, mock_diff):
        """完整的執行流程應該正確計算信心分數"""
        mock_diff.return_value = "diff --git a/file.py b/file.py\n+def test():"
        mock_files.return_value = ["file.py"]
        mock_funcs.return_value = ["def test()"]

        hook = SkillGeneratorHook()
        ctx = TaskContext(
            status="completed",
            project_path="/tmp",
            project_name="test",
            card_title="Test",
            card_id=1,
            output="A" * 150,
            exit_code=0,
        )
        hook.on_complete(ctx)

        # 信心分數應該被設置
        assert ctx.confidence_score == pytest.approx(1.0, abs=1e-9)
        # 應該調用 _save_skill
        mock_save.assert_called_once()
