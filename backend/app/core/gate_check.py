"""
Build Gate — 在 stage action 執行前做語法檢查閘門

只檢查工作區中變更過的 .py 檔案（透過 git diff），
用 py_compile 逐一做語法驗證。
"""
import subprocess
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

from app.core.lint_rules import LintViolation, run_lint_rules

logger = logging.getLogger(__name__)

GATE_TIMEOUT = 30  # 秒


@dataclass(frozen=True)
class GateResult:
    passed: bool
    message: str


def _get_changed_py_files(workspace_path: str) -> list[str]:
    """取得工作區中 git 追蹤到的變更 .py 檔案清單"""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=ACM", "HEAD"],
            cwd=workspace_path,
            capture_output=True,
            text=True,
            timeout=GATE_TIMEOUT,
        )
        files = [
            f.strip() for f in result.stdout.splitlines()
            if f.strip().endswith(".py")
        ]
        return files
    except subprocess.TimeoutExpired:
        logger.warning("[Gate] git diff timed out after %ds", GATE_TIMEOUT)
        return []
    except OSError as e:
        logger.warning("[Gate] Failed to get changed files: %s", e)
        return []


def run_build_gate(workspace_path: str, project_id: int) -> GateResult:
    """對工作區變更的 .py 檔案執行 py_compile 語法檢查。

    Args:
        workspace_path: 工作區絕對路徑
        project_id: 專案 ID（預留，供未來擴充使用）

    Returns:
        GateResult(passed=True/False, message=說明)
    """
    ws = Path(workspace_path)
    if not ws.exists():
        return GateResult(passed=True, message="workspace not found, skip gate")

    changed_files = _get_changed_py_files(workspace_path)
    if not changed_files:
        return GateResult(passed=True, message="no changed .py files")

    errors: list[str] = []
    for rel_path in changed_files:
        full_path = ws / rel_path
        if not full_path.exists():
            continue
        # 防止 path traversal（git diff 可能回傳 ../.. 路徑）
        if not str(full_path.resolve()).startswith(str(ws.resolve())):
            errors.append(f"{rel_path}: path traversal blocked")
            continue
        try:
            result = subprocess.run(
                [sys.executable, "-m", "py_compile", str(full_path)],
                capture_output=True,
                text=True,
                timeout=GATE_TIMEOUT,
            )
            if result.returncode != 0:
                err_msg = result.stderr.strip() or result.stdout.strip()
                errors.append(f"{rel_path}: {err_msg}")
        except subprocess.TimeoutExpired:
            errors.append(f"{rel_path}: compile check timeout ({GATE_TIMEOUT}s)")
        except Exception as e:
            errors.append(f"{rel_path}: {e}")

    if errors:
        detail = "\n".join(errors)
        return GateResult(
            passed=False,
            message=f"Build gate failed — {len(errors)} file(s) with syntax errors:\n{detail}",
        )

    # --- Lint rules ---
    all_violations: list[LintViolation] = []
    for rel_path in changed_files:
        full_path = ws / rel_path
        if full_path.exists():
            all_violations.extend(run_lint_rules(str(full_path)))

    lint_errors = [v for v in all_violations if v.severity == "error"]
    lint_warnings = [v for v in all_violations if v.severity == "warning"]

    def _format_violation(v: LintViolation) -> str:
        return f"  [{v.severity.upper()}] {v.file}:{v.line} {v.rule_id} — {v.message}\n    fix: {v.fix_hint}"

    lint_detail = "\n".join(_format_violation(v) for v in all_violations)

    if lint_errors:
        msg = f"Build gate failed — {len(lint_errors)} lint error(s)"
        if lint_warnings:
            msg += f", {len(lint_warnings)} warning(s)"
        return GateResult(
            passed=False,
            message=f"{msg}:\n{lint_detail}",
        )

    base_msg = f"Build gate passed — {len(changed_files)} file(s) checked"
    if lint_warnings:
        base_msg += f" ({len(lint_warnings)} lint warning(s))"
        base_msg += f"\n{lint_detail}"

    return GateResult(passed=True, message=base_msg)
