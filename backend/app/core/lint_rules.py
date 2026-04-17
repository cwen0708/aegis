"""
Lint Rules — 可擴充的自訂 Lint 規則框架

每條規則實作 LintRule Protocol，回傳 LintViolation 含修正指引（fix_hint）。
severity: "warning" 不阻擋 gate，"error" 會阻擋。
"""
import ast
import re
from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True)
class LintViolation:
    file: str
    line: int
    rule_id: str
    message: str
    fix_hint: str
    severity: Literal["warning", "error"]


class LintRule(Protocol):
    def check(self, file_path: str, content: str) -> list[LintViolation]: ...


# ---------------------------------------------------------------------------
# Rule implementations
# ---------------------------------------------------------------------------

class FileLengthRule:
    """檔案超過 800 行 -> warning"""

    MAX_LINES = 800

    def check(self, file_path: str, content: str) -> list[LintViolation]:
        line_count = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
        if line_count > self.MAX_LINES:
            return [
                LintViolation(
                    file=file_path,
                    line=line_count,
                    rule_id="file-length",
                    message=f"File has {line_count} lines (max {self.MAX_LINES})",
                    fix_hint="建議拆分模組，將相關功能提取到獨立檔案以降低單檔複雜度",
                    severity="warning",
                ),
            ]
        return []


class BareExceptRule:
    """偵測裸 except: -> error"""

    _PATTERN = re.compile(r"^\s*except\s*:", re.MULTILINE)

    def check(self, file_path: str, content: str) -> list[LintViolation]:
        violations: list[LintViolation] = []
        for i, line in enumerate(content.splitlines(), start=1):
            if self._PATTERN.match(line):
                violations.append(
                    LintViolation(
                        file=file_path,
                        line=i,
                        rule_id="bare-except",
                        message="Bare `except:` catches all exceptions including KeyboardInterrupt",
                        fix_hint="指定具體例外類型，例如 `except ValueError:` 或至少使用 `except Exception:`",
                        severity="error",
                    ),
                )
        return violations


class MutableDefaultRule:
    """偵測 def foo(x=[]) 或 def foo(x={}) -> error"""

    def check(self, file_path: str, content: str) -> list[LintViolation]:
        try:
            tree = ast.parse(content, filename=file_path)
        except SyntaxError:
            return []

        violations: list[LintViolation] = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for default in node.args.defaults + node.args.kw_defaults:
                if default is None:
                    continue
                if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                    violations.append(
                        LintViolation(
                            file=file_path,
                            line=default.lineno,
                            rule_id="mutable-default",
                            message=f"Mutable default argument in `{node.name}()`",
                            fix_hint="使用 None 作為預設值，並在函式內初始化：`if x is None: x = []`",
                            severity="error",
                        ),
                    )
        return violations


# ---------------------------------------------------------------------------
# Registry & entry point
# ---------------------------------------------------------------------------

DEFAULT_RULES: list[LintRule] = [
    FileLengthRule(),
    BareExceptRule(),
    MutableDefaultRule(),
]


def run_lint_rules(
    file_path: str,
    *,
    rules: list[LintRule] | None = None,
) -> list[LintViolation]:
    """對單一檔案執行所有 lint 規則，回傳違規清單。

    Args:
        file_path: 檔案路徑（絕對或相對）
        rules: 自訂規則清單，預設使用 DEFAULT_RULES
    """
    from pathlib import Path

    path = Path(file_path)
    if not path.exists():
        return []

    content = path.read_text(encoding="utf-8", errors="replace")
    active_rules = rules if rules is not None else DEFAULT_RULES

    violations: list[LintViolation] = []
    for rule in active_rules:
        violations.extend(rule.check(file_path, content))

    return violations
