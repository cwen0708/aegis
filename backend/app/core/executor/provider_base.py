"""
Provider 抽象介面 — 定義所有 LLM Provider 的統一合約

每個 Provider 負責：
1. 組裝 CLI 命令（build_command）
2. 解析串流輸出（parse_stream_line）
3. 解析完整輸出的 token 用量（parse_output）
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Tuple


@dataclass(frozen=True)
class ProviderMeta:
    """Provider 的靜態設定描述。"""
    name: str
    default_model: str = ""
    stream_json: bool = False
    json_output: bool = False
    stdin_prompt: bool = False


class BaseProvider(ABC):
    """所有 LLM Provider 的抽象基底類別。"""

    @property
    @abstractmethod
    def meta(self) -> ProviderMeta:
        """回傳 Provider 的靜態設定。"""

    @abstractmethod
    def build_command(
        self,
        prompt: str = "",
        model: str = "",
        *,
        mode: Literal["task", "chat"] = "task",
        mcp_config_path: Optional[str] = None,
        resume_session_id: Optional[str] = None,
    ) -> Tuple[List[str], bool]:
        """組裝 CLI 命令。

        Returns:
            (cmd_parts, stdin_prompt) — 命令列表和是否需要 stdin 傳 prompt
        """

    @abstractmethod
    def parse_stream_line(self, line: str) -> Optional[str]:
        """從串流輸出單行提取文字內容。

        Returns:
            提取的文字，或 None（非文字行或解析失敗）
        """

    @abstractmethod
    def parse_output(self, output: str) -> Dict[str, Any]:
        """從完整輸出解析結果文字與 token 用量。

        Returns:
            包含 result_text, model, input_tokens, output_tokens 等的 dict，
            解析失敗時回傳空 dict。
        """

    # ── 便利方法 ──

    def to_legacy_config(self) -> dict:
        """轉換為舊版 PROVIDERS dict 格式，供過渡期相容使用。"""
        m = self.meta
        cfg: dict = {"cmd_base": [m.name]}
        if m.stream_json:
            cfg["stream_json"] = True
        if m.json_output:
            cfg["json_output"] = True
        if m.default_model:
            cfg["default_model"] = m.default_model
        if m.stdin_prompt:
            cfg["stdin_prompt"] = True
        return cfg
