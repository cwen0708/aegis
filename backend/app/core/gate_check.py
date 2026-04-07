"""
Build Gate — 在 stage action 執行前做語法檢查閘門

只檢查工作區中變更過的 .py 檔案（透過 git diff），
用 py_compile 逐一做語法驗證。
"""
import subprocess
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("aegis.gate_check")

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
    except (subprocess.TimeoutExpired, Exception) as e:
        logger.warning(f"[Gate] Failed to get changed files: {e}")
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
        try:
            result = subprocess.run(
                ["python", "-m", "py_compile", str(full_path)],
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

    return GateResult(
        passed=True,
        message=f"Build gate passed — {len(changed_files)} file(s) checked",
    )
