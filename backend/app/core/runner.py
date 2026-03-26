"""
Runner — 輕量 AI 呼叫器（僅供即時互動場景使用）

⚠️ 此模組【不負責】卡片任務執行。卡片任務由獨立的 worker.py 程序處理，
   worker.py 擁有完整的 PTY 串流、帳號 fallback、心跳、CronLog 等機制。

此模組的使用者：
- chat_handler.py — Bot 即時對話（Telegram/LINE 等）
- email_processor.py — Email AI 分類

這些場景不需要 PTY 串流或帳號 fallback，只需簡單的 prompt → response。
"""
import asyncio
import subprocess
import re
import logging
from typing import Dict, Any, Optional, Callable

from app.core.executor import PROVIDERS, build_command
from app.core.executor.providers import get_provider_config
from app.core.executor.auth import get_mcp_config_path

logger = logging.getLogger(__name__)

# Channel-send 標記格式：
# [CH_EDIT:platform:chat_id:message_id:文字內容]
# [CH_SEND:platform:chat_id:文字內容]
# 結尾的 ] 可選（AI 長訊息可能不閉合）
_CH_EDIT_RE = re.compile(r'\[CH_EDIT:([^:]+):([^:]+):([^:]+):(.*?)(?:\]|$)', re.DOTALL)
_CH_SEND_RE = re.compile(r'\[CH_SEND:([^:]+):([^:]+):(.*?)(?:\]|$)', re.DOTALL)


from app.core.stream_parsers import (  # noqa: E402
    parse_stream_json_text as _parse_stream_json_text,
    parse_stream_json_tokens as _parse_stream_json_tokens,
    parse_claude_json as _parse_claude_json,
)


def _intercept_channel_marker(line: str):
    """即時攔截輸出中的 channel-send 標記，非同步發送訊息"""
    from app.core.http_client import InternalAPI

    for pattern, has_edit_id in [(_CH_EDIT_RE, True), (_CH_SEND_RE, False)]:
        m = pattern.search(line)
        if not m:
            continue
        if has_edit_id:
            platform, chat_id, edit_id, text = m.group(1), m.group(2), m.group(3), m.group(4)
        else:
            platform, chat_id, text = m.group(1), m.group(2), m.group(3)
            edit_id = None

        InternalAPI.channel_send_async(platform, chat_id, text, edit_id)
        return


async def run_ai_task(task_id: int, project_path: str, prompt: str, phase: str,
                      forced_provider: Optional[str] = None, card_title: str = "",
                      project_name: str = "", member_id: Optional[int] = None,
                      model_override: Optional[str] = None,
                      project_id: Optional[int] = None,
                      auth_info: Optional[Dict[str, str]] = None,
                      extra_env: Optional[Dict[str, str]] = None,
                      on_stream: Optional[Callable[[str], None]] = None,
                      resume_session_id: Optional[str] = None,
                      use_process_pool: bool = False,
                      chat_key: Optional[str] = None,
                      cwd: Optional[str] = None) -> Dict[str, Any]:
    """
    執行單一 AI 呼叫（用於 chat / email 等即時場景）。

    注意：卡片任務不走這裡，由 worker.py 負責。
    """
    if use_process_pool and chat_key:
        from app.core.session_pool import process_pool
        logger.info(f"[Runner] ProcessPool path: key={chat_key} model={model_override}")
        return await asyncio.to_thread(
            process_pool.send_message,
            chat_key=chat_key,
            message=prompt,
            model=model_override or "haiku",
            member_id=member_id,
            auth_info=auth_info,
            extra_env=extra_env,
            on_line=on_stream,
            cwd=cwd,
        )

    # Prompt Hardening: 非 pool 路徑也注入安全提醒
    from app.core.prompt_hardening import harden_prompt
    prompt = harden_prompt(prompt, project_path)

    # Data Classification Guard：送往 AI 前掃描敏感資料
    from app.core.data_classifier import guard_for_ai, SecurityBlock
    try:
        prompt, _redact_map = guard_for_ai(prompt)
    except SecurityBlock as e:
        logger.warning(f"[Runner] Prompt blocked by security guard: {e}")
        return {"status": "error", "output": f"SecurityBlock: {e}", "provider": forced_provider or "claude"}

    provider_name = forced_provider if forced_provider and forced_provider in PROVIDERS else "claude"
    config = get_provider_config(provider_name)

    # 透過 executor 建構命令（統一 provider 設定）
    mcp_path = get_mcp_config_path(member_id) if member_id and provider_name == "claude" else None
    cmd, stdin_prompt = build_command(
        provider=provider_name,
        prompt=prompt,
        model=model_override or "",
        mode="chat",
        mcp_config_path=mcp_path,
        resume_session_id=resume_session_id,
    )

    from app.core.sandbox import get_popen_kwargs
    from app.core.env_builder import EnvironmentBuilder

    env = (EnvironmentBuilder()
        .with_system_keys()
        .with_project_vars(project_id)
        .with_global_api_keys()
        .with_member_extra(extra_env)
        .with_auth(provider_name, auth_info or {})
        .build())

    # 移除舊的環境變數組裝邏輯，已統一到 EnvironmentBuilder

    logger.info(f"[Runner] Executing {provider_name} (task_id={task_id}, phase={phase})")

    try:
        popen_kwargs = get_popen_kwargs()
        proc = subprocess.Popen(
            cmd,
            cwd=project_path,
            stdin=subprocess.PIPE if stdin_prompt else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            **popen_kwargs,
        )
        if stdin_prompt and proc.stdin:
            proc.stdin.write(prompt.encode("utf-8"))
            proc.stdin.close()

        is_stream_json = config.get("stream_json", False)
        result_text_parts = []
        stream_token_info = {}

        def _read_output():
            lines = []
            for raw_line in proc.stdout:
                line = raw_line.decode("utf-8", errors="replace")
                lines.append(line)

                if is_stream_json:
                    # stream-json 模式：逐行解析文字、即時攔截標記
                    clean = line.strip()
                    if clean.startswith("{"):
                        text = _parse_stream_json_text(clean)
                        if text:
                            result_text_parts.append(text)
                            # 即時攔截 channel-send 標記
                            for tl in text.split("\n"):
                                _intercept_channel_marker(tl.strip())
                        # 收集 token info（從 result 行）
                        ti = _parse_stream_json_tokens(clean)
                        if ti:
                            nonlocal stream_token_info
                            stream_token_info = ti
                        # 即時串流回呼（工具呼叫翻譯）
                        if on_stream:
                            on_stream(clean)
                elif not config.get("json_output"):
                    _intercept_channel_marker(line.strip())
            proc.wait()
            return lines

        try:
            output_lines = await asyncio.wait_for(
                asyncio.to_thread(_read_output),
                timeout=600,  # chat/email 10 分鐘超時（比卡片任務短）
            )
        except asyncio.TimeoutError:
            proc.kill()
            proc.wait()
            return {"status": "timeout", "output": "任務超時 (10 分鐘)", "provider": provider_name}

        output = "".join(output_lines)
        status = "success" if proc.returncode == 0 else "error"

        token_info = {}
        actual_output = output
        if provider_name == "claude":
            if is_stream_json and result_text_parts:
                # stream-json 模式：用逐行收集的文字（標記已即時攔截）
                actual_output = "".join(result_text_parts)
                token_info = stream_token_info
            else:
                # 舊 JSON 模式 fallback
                token_info = _parse_claude_json(output)
                if token_info.get("result_text"):
                    actual_output = token_info["result_text"]
                # 後處理標記
                for tl in actual_output.split("\n"):
                    _intercept_channel_marker(tl.strip())
        elif provider_name == "openai":
            if is_stream_json and result_text_parts:
                actual_output = "".join(result_text_parts)
                token_info = stream_token_info
            elif config.get("json_output"):
                from app.core.stream_parsers import parse_openai_json
                token_info = parse_openai_json(output)
                if token_info.get("result_text"):
                    actual_output = token_info["result_text"]

        return {
            "status": status,
            "output": actual_output,
            "provider": provider_name,
            "exit_code": proc.returncode,
            "token_info": token_info,
            "session_id": token_info.get("session_id"),
        }

    except Exception as e:
        logger.exception(f"[Runner] Execution failed: {e}")
        return {"status": "error", "output": str(e), "provider": provider_name}
