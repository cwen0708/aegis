"""
OpenAI Provider — 封裝 OpenAI CLI wrapper 的命令建構與輸出解析
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Literal, Optional, Tuple

from app.core.executor.provider_base import BaseProvider, ProviderMeta


class OpenAIProvider(BaseProvider):
    """OpenAI Provider 實作。

    透過 scripts/openai_stream_chat.py wrapper 與 OpenAI API 互動，
    輸出格式為 stream-json（與 Claude CLI 相容）或 OpenAI SSE。
    """

    _meta = ProviderMeta(
        name="openai",
        default_model="gpt-4o",
        stream_json=True,
        stdin_prompt=True,
    )

    @property
    def meta(self) -> ProviderMeta:
        return self._meta

    def build_command(
        self,
        prompt: str = "",
        model: str = "",
        *,
        mode: Literal["task", "chat"] = "task",
        mcp_config_path: Optional[str] = None,
        resume_session_id: Optional[str] = None,
    ) -> Tuple[List[str], bool]:
        resolved_model = model or self._meta.default_model
        cmd = ["python", "backend/scripts/openai_stream_chat.py", "--model", resolved_model]
        return cmd, True  # prompt 從 stdin 傳入

    def parse_stream_line(self, line: str) -> Optional[str]:
        """解析 OpenAI SSE 格式的串流行。

        支援兩種格式：
        - stream-json（wrapper 輸出）：{"type": "assistant", "content": [...]}
        - 原生 SSE：data: {"choices":[{"delta":{"content":"..."}}]}
        """
        stripped = line.strip()
        if not stripped:
            return None

        # stream-json 格式（由 openai_stream_chat.py 輸出）
        if stripped.startswith("{"):
            try:
                data = json.loads(stripped)
                if data.get("type") == "assistant":
                    content = data.get("content", []) or data.get("message", {}).get("content", [])
                    if isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "text":
                                return block.get("text", "")
            except (json.JSONDecodeError, KeyError, TypeError):
                pass
            return None

        # 原生 OpenAI SSE 格式
        if stripped.startswith("data:"):
            payload = stripped[5:].strip()
            if payload == "[DONE]":
                return None
            try:
                data = json.loads(payload)
                choices = data.get("choices")
                if isinstance(choices, list) and choices:
                    delta = choices[0].get("delta", {})
                    content = delta.get("content")
                    if content:
                        return content
            except (json.JSONDecodeError, KeyError, TypeError, IndexError):
                pass
        return None

    def parse_output(self, output: str) -> Dict[str, Any]:
        """解析 OpenAI wrapper 的完整 JSON 輸出。

        支援兩種格式：
        - 多行 stream-json：逐行掃描找 type=result 的行
        - 單一 JSON（舊格式）：直接解析整段輸出
        """
        # 多行 stream-json：逐行掃描找 type=result
        for line in output.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                if data.get("type") == "result":
                    usage = data.get("usage", {})
                    return {
                        "result_text": data.get("result", ""),
                        "model": data.get("model", ""),
                        "duration_ms": data.get("duration_ms", 0),
                        "cost_usd": data.get("total_cost_usd", 0),
                        "input_tokens": usage.get("input_tokens", 0),
                        "output_tokens": usage.get("output_tokens", 0),
                    }
            except (json.JSONDecodeError, ValueError):
                continue

        # 舊格式 fallback：單一 JSON，key 在頂層
        try:
            data = json.loads(output.strip())
            return {
                "result_text": data.get("result_text", ""),
                "model": data.get("model", ""),
                "duration_ms": data.get("duration_ms", 0),
                "cost_usd": data.get("cost_usd", 0),
                "input_tokens": data.get("input_tokens", 0),
                "output_tokens": data.get("output_tokens", 0),
            }
        except (json.JSONDecodeError, KeyError):
            return {}
