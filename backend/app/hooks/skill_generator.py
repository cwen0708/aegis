"""SkillGeneratorHook — 任務完成後自動分析 git diff 並生成 skill 模板"""
import logging
import os
import re
import subprocess
from datetime import datetime

from app.hooks import Hook, TaskContext

logger = logging.getLogger(__name__)


class SkillGeneratorHook(Hook):
    """在開發任務完成後，自動從 git diff 生成 skill 模板檔案。"""

    def on_complete(self, ctx: TaskContext) -> None:
        if ctx.status != "completed":
            # 失敗狀態的信心分數為 0
            ctx.confidence_score = 0.0
            return
        if not ctx.project_path:
            return

        try:
            diff_text = self._get_git_diff(ctx.project_path)
            if not diff_text:
                logger.debug("[SkillGeneratorHook] no diff found, skipping")
                return

            changed_files = self._extract_changed_files(diff_text)
            new_functions = self._extract_new_functions(diff_text)

            # 計算信心分數
            ctx.confidence_score = self._calculate_confidence(ctx)

            commit_hash = self._get_commit_hash(ctx.project_path)
            skill_md = self._build_skill_template(ctx, changed_files, new_functions, commit_hash)
            self._save_skill(ctx.member_slug, skill_md, ctx.project_path)
        except Exception as e:
            logger.warning(f"[SkillGeneratorHook] failed: {e}")

    # ── 內部方法 ──────────────────────────────────────────────

    def _calculate_confidence(self, ctx: TaskContext) -> float:
        """
        計算信心分數（0.0-1.0），用以評估該 pattern 的可靠性。

        計分規則：
        - exit_code == 0: +0.5
        - output 長度 > 100 字: +0.2
        - 執行時間合理 (無超時): +0.2
        - 無異常/警告: +0.1
        """
        score = 0.0

        # 1. exit_code == 0: +0.5
        if ctx.exit_code == 0:
            score += 0.5

        # 2. output 長度 > 100 字: +0.2
        if len(ctx.output) > 100:
            score += 0.2

        # 3. 執行時間合理（檢查是否無超時相關的錯誤）: +0.2
        timeout_keywords = [
            "timeout",
            "timed out",
            "time limit exceeded",
            "max time",
            "deadline",
        ]
        has_timeout = any(keyword.lower() in ctx.output.lower() for keyword in timeout_keywords)
        if not has_timeout:
            score += 0.2

        # 4. 無異常/警告: +0.1
        error_keywords = ["exception", "error", "traceback", "failed"]
        has_error = any(keyword.lower() in ctx.output.lower() for keyword in error_keywords)
        if not has_error:
            score += 0.1

        # 限制在 0.0-1.0 範圍內
        return min(max(score, 0.0), 1.0)

    def _get_commit_hash(self, project_path: str) -> str:
        """取得目前 git commit 的短 hash，失敗時回傳空字串。"""
        if not project_path:
            return ""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=project_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.stdout.strip() or ""
        except Exception:
            return ""

    def _get_git_diff(self, project_path: str) -> str:
        """對比 origin/main 取得 diff 文字。"""
        try:
            result = subprocess.run(
                ["git", "diff", "origin/main...HEAD"],
                cwd=project_path,
                capture_output=True,
                text=True,
                timeout=30,
            )
            return result.stdout or ""
        except subprocess.TimeoutExpired:
            logger.warning("[SkillGeneratorHook] git diff timeout")
            return ""
        except FileNotFoundError:
            logger.warning("[SkillGeneratorHook] git not found")
            return ""

    def _extract_changed_files(self, diff_text: str) -> list[str]:
        """從 diff 提取修改的檔案清單。"""
        files = []
        for line in diff_text.splitlines():
            if line.startswith("diff --git "):
                # diff --git a/path/to/file.py b/path/to/file.py
                match = re.search(r"b/(.+)$", line)
                if match:
                    files.append(match.group(1))
        return list(dict.fromkeys(files))  # 去重保序

    def _extract_new_functions(self, diff_text: str) -> list[str]:
        """從 diff 提取新增的函式/方法簽名。"""
        signatures = []
        # 僅看「+」行（新增），匹配 Python def 與 TypeScript/JS function/async function/箭頭函式
        patterns = [
            r"^\+\s+((?:async\s+)?def\s+\w+\s*\([^)]*\))",          # Python
            r"^\+\s+((?:export\s+)?(?:async\s+)?function\s+\w+\s*\([^)]*\))",  # JS/TS function
            r"^\+\s+((?:async\s+)?\w+\s*\([^)]*\)\s*(?::\s*\w+)?\s*\{)",       # TS method
        ]
        for line in diff_text.splitlines():
            for pat in patterns:
                m = re.match(pat, line)
                if m:
                    sig = m.group(1).strip().rstrip("{").strip()
                    if sig not in signatures:
                        signatures.append(sig)
                    break
        return signatures[:20]  # 最多 20 筆，避免過長

    def _build_skill_template(
        self,
        ctx: TaskContext,
        changed_files: list[str],
        new_functions: list[str],
        commit_hash: str = "",
    ) -> str:
        """生成 Markdown 格式的 skill 模板。"""
        now = datetime.now().strftime("%Y-%m-%d")

        files_md = "\n".join(f"- `{f}`" for f in changed_files) if changed_files else "（無）"
        funcs_md = "\n".join(f"- `{f}`" for f in new_functions) if new_functions else "（無）"

        # 信心分數信息
        confidence_pct = int(ctx.confidence_score * 100)
        confidence_note = f"此 skill 的信心分數為 {confidence_pct}%（{ctx.confidence_score:.2f}/1.0），評估該 pattern 的可靠性。"

        commit_line = f"\ncommit_hash: {commit_hash}" if commit_hash else ""

        return f"""---
name: {ctx.card_title or "auto-generated-skill"}
description: 自動生成於任務「{ctx.card_title}」完成後（{now}）
generated_from_card: {ctx.card_id}
generated_at: {now}
project: {ctx.project_name}
confidence_score: {ctx.confidence_score:.2f}{commit_line}
---

# {ctx.card_title}

> 此 skill 由 SkillGeneratorHook 自動生成，請依實際需求調整。
>
> **信心分數：{confidence_pct}%** — {confidence_note}

## 修改的檔案

{files_md}

## 新增的函式 / 方法

{funcs_md}

## 使用說明

<!-- TODO: 補充此 skill 的使用時機與步驟 -->

1. 說明何時應使用此 skill
2. 列出前置條件（環境、權限…）
3. 列出執行步驟

## 注意事項

<!-- TODO: 列出已知限制或需特別留意的地方 -->
"""

    def _save_skill(self, member_slug: str, content: str, project_path: str = "") -> None:
        """將 skill 模板寫入目標目錄。

        - 有 member_slug：寫入 .aegis/members/{slug}/skills/drafts/
        - 無 member_slug（fallback）：寫入 {project_path}/.claude/skills/
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"skill_generated_{timestamp}.md"

        if member_slug:
            from app.core.member_profile import get_skills_drafts_dir, get_member_dir
            # 確保 drafts/ 與 active/ 都已建立
            get_member_dir(member_slug)
            drafts_dir = get_skills_drafts_dir(member_slug)
            filepath = drafts_dir / filename
            filepath.write_text(content, encoding="utf-8")
            logger.info(f"[SkillGeneratorHook] skill saved to drafts: {filepath}")
        else:
            # fallback：舊路徑
            skills_dir = os.path.join(project_path, ".claude", "skills")
            os.makedirs(skills_dir, exist_ok=True)
            filepath_str = os.path.join(skills_dir, filename)
            with open(filepath_str, "w", encoding="utf-8") as f:
                f.write(content)
            logger.info(f"[SkillGeneratorHook] skill saved (legacy): {filepath_str}")
