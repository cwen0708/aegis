"""TastePropagationHook — 單元測試"""
from pathlib import Path

from app.hooks import TaskContext
from app.hooks.taste_propagation import (
    TastePropagationHook,
    _FRONTMATTER,
    _read_existing_rules,
)


def _make_ctx(output: str, member_slug: str = "test-member") -> TaskContext:
    return TaskContext(output=output, member_slug=member_slug)


class TestTasteExtraction:
    """輸出含 taste 標記 → 規則被萃取寫入"""

    def test_single_taste_written(self, tmp_path, monkeypatch):
        """單一 taste 標記應寫入 golden-rules.md"""
        monkeypatch.setattr(
            "app.core.member_profile.get_member_dir",
            lambda slug: tmp_path,
        )
        hook = TastePropagationHook()
        ctx = _make_ctx("結果報告\n<!-- taste: 函式不超過 50 行 -->\n完成")

        hook.on_complete(ctx)

        rules_path = tmp_path / "golden-rules.md"
        assert rules_path.exists()
        content = rules_path.read_text(encoding="utf-8")
        assert "- 函式不超過 50 行" in content

    def test_multiple_tastes_all_extracted(self, tmp_path, monkeypatch):
        """多條 taste 標記應全部萃取"""
        monkeypatch.setattr(
            "app.core.member_profile.get_member_dir",
            lambda slug: tmp_path,
        )
        hook = TastePropagationHook()
        output = (
            "<!-- taste: 禁止使用 any 型別 -->\n"
            "中間內容\n"
            "<!-- taste: 錯誤訊息必須包含上下文 -->\n"
            "<!-- taste: 測試覆蓋率至少 80% -->\n"
        )
        ctx = _make_ctx(output)

        hook.on_complete(ctx)

        rules_path = tmp_path / "golden-rules.md"
        content = rules_path.read_text(encoding="utf-8")
        assert "- 禁止使用 any 型別" in content
        assert "- 錯誤訊息必須包含上下文" in content
        assert "- 測試覆蓋率至少 80%" in content


class TestNoTaste:
    """輸出不含 taste → 不產生任何檔案"""

    def test_no_taste_no_file(self, tmp_path, monkeypatch):
        """無 taste 標記時不建立 golden-rules.md"""
        monkeypatch.setattr(
            "app.core.member_profile.get_member_dir",
            lambda slug: tmp_path,
        )
        hook = TastePropagationHook()
        ctx = _make_ctx("一切正常，沒有 taste 標記")

        hook.on_complete(ctx)

        rules_path = tmp_path / "golden-rules.md"
        assert not rules_path.exists()

    def test_empty_output_no_file(self, tmp_path, monkeypatch):
        """空輸出不建立檔案"""
        monkeypatch.setattr(
            "app.core.member_profile.get_member_dir",
            lambda slug: tmp_path,
        )
        hook = TastePropagationHook()
        ctx = _make_ctx("")

        hook.on_complete(ctx)

        rules_path = tmp_path / "golden-rules.md"
        assert not rules_path.exists()

    def test_no_member_slug_skip(self, tmp_path):
        """無 member_slug 時跳過"""
        hook = TastePropagationHook()
        ctx = _make_ctx("<!-- taste: 規則 -->", member_slug="")

        hook.on_complete(ctx)
        # 不應發生任何寫入（無 monkeypatch 也不會報錯）


class TestDeduplication:
    """重複規則 → 不重複寫入"""

    def test_duplicate_in_same_output(self, tmp_path, monkeypatch):
        """同一次輸出中重複的 taste 只寫入一次"""
        monkeypatch.setattr(
            "app.core.member_profile.get_member_dir",
            lambda slug: tmp_path,
        )
        hook = TastePropagationHook()
        output = (
            "<!-- taste: 變數命名用 snake_case -->\n"
            "<!-- taste: 變數命名用 snake_case -->\n"
        )
        ctx = _make_ctx(output)

        hook.on_complete(ctx)

        rules_path = tmp_path / "golden-rules.md"
        content = rules_path.read_text(encoding="utf-8")
        assert content.count("- 變數命名用 snake_case") == 1

    def test_duplicate_across_runs(self, tmp_path, monkeypatch):
        """跨次執行的重複規則不重複寫入"""
        monkeypatch.setattr(
            "app.core.member_profile.get_member_dir",
            lambda slug: tmp_path,
        )

        # 第一次執行
        hook1 = TastePropagationHook()
        ctx1 = _make_ctx("<!-- taste: 禁止硬編碼密鑰 -->")
        hook1.on_complete(ctx1)

        # 第二次執行（相同規則）
        hook2 = TastePropagationHook()
        ctx2 = _make_ctx("<!-- taste: 禁止硬編碼密鑰 -->")
        hook2.on_complete(ctx2)

        rules_path = tmp_path / "golden-rules.md"
        content = rules_path.read_text(encoding="utf-8")
        assert content.count("- 禁止硬編碼密鑰") == 1

    def test_new_rule_appended_to_existing(self, tmp_path, monkeypatch):
        """新規則應 append 到已有規則之後"""
        monkeypatch.setattr(
            "app.core.member_profile.get_member_dir",
            lambda slug: tmp_path,
        )

        # 第一次
        hook1 = TastePropagationHook()
        ctx1 = _make_ctx("<!-- taste: 規則 A -->")
        hook1.on_complete(ctx1)

        # 第二次（不同規則）
        hook2 = TastePropagationHook()
        ctx2 = _make_ctx("<!-- taste: 規則 B -->")
        hook2.on_complete(ctx2)

        rules_path = tmp_path / "golden-rules.md"
        content = rules_path.read_text(encoding="utf-8")
        assert "- 規則 A" in content
        assert "- 規則 B" in content


class TestFrontmatter:
    """golden-rules.md 格式正確"""

    def test_new_file_has_frontmatter(self, tmp_path, monkeypatch):
        """新建的 golden-rules.md 包含 YAML frontmatter"""
        monkeypatch.setattr(
            "app.core.member_profile.get_member_dir",
            lambda slug: tmp_path,
        )
        hook = TastePropagationHook()
        ctx = _make_ctx("<!-- taste: 測試規則 -->")

        hook.on_complete(ctx)

        rules_path = tmp_path / "golden-rules.md"
        content = rules_path.read_text(encoding="utf-8")
        assert content.startswith("---\n")
        assert "name: golden-rules" in content

    def test_existing_file_preserves_frontmatter(self, tmp_path, monkeypatch):
        """已存在的 golden-rules.md 保留原有 frontmatter"""
        monkeypatch.setattr(
            "app.core.member_profile.get_member_dir",
            lambda slug: tmp_path,
        )
        # 預先建立含 frontmatter 的檔案
        rules_path = tmp_path / "golden-rules.md"
        rules_path.write_text(
            _FRONTMATTER + "- 既有規則\n",
            encoding="utf-8",
        )

        hook = TastePropagationHook()
        ctx = _make_ctx("<!-- taste: 新規則 -->")
        hook.on_complete(ctx)

        content = rules_path.read_text(encoding="utf-8")
        assert "- 既有規則" in content
        assert "- 新規則" in content


class TestReadExistingRules:
    """_read_existing_rules 輔助函式"""

    def test_reads_rules_from_file(self, tmp_path):
        path = tmp_path / "golden-rules.md"
        path.write_text(
            _FRONTMATTER + "- 規則一\n- 規則二\n",
            encoding="utf-8",
        )
        rules = _read_existing_rules(path)
        assert rules == {"規則一", "規則二"}

    def test_nonexistent_file_returns_empty(self, tmp_path):
        path = tmp_path / "nonexistent.md"
        rules = _read_existing_rules(path)
        assert rules == set()
