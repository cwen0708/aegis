"""
Task Result Handlers — 卡片任務結果處理

從 worker.py 拆出，依卡片類型分派：
- handle_chat_result(): Chat 卡片 → aegis_stream + 刪除
- handle_cron_result(): 排程卡片 → CronLog + stage action
- handle_regular_result(): 一般卡片 → 追加輸出 + stage action + git
- post_task_hooks(): 共用後處理（廣播/dialogue/OneStack/記憶/清理）
"""
import json
import logging
import re
from typing import Optional

from sqlmodel import Session

from app.database import engine
from app.models.core import CardIndex, StageList

logger = logging.getLogger(__name__)


def handle_chat_result(idx, result, new_status, token_info, member_slug, chat_id,
                       *, broadcast_event, delete_card_completely):
    """Chat 卡片結果處理：寫入 aegis_stream + 刪除卡片"""
    raw_output = result.get("output", "")
    output_text = token_info.get("result_text", "")
    if not output_text:
        output_text = _extract_chat_output(raw_output)
    if not output_text:
        output_text = raw_output[:3000]

    # OneStack stream
    try:
        from app.core.onestack_connector import connector
        if connector.enabled and chat_id:
            import threading, asyncio as _aio
            evt_type = "result" if new_status == "completed" else "error"
            def _stream():
                try:
                    loop = _aio.new_event_loop()
                    loop.run_until_complete(
                        connector.stream_event(idx.card_id, evt_type, output_text[:3000], member_slug, chat_id=chat_id)
                    )
                    loop.close()
                except Exception:
                    pass
            threading.Thread(target=_stream, daemon=True).start()
    except Exception:
        pass

    # 註冊 session
    _new_sid = token_info.get("session_id")
    if _new_sid and chat_id:
        from app.core.session_pool import session_pool as _sp
        _sp.register(chat_id, _new_sid)

    delete_card_completely(idx.card_id)
    logger.info(f"[Task] Chat card {idx.card_id} {new_status}, deleted")
    broadcast_event("task_completed" if new_status == "completed" else "task_failed",
                    {"card_id": idx.card_id, "status": new_status})


def handle_cron_result(idx, result, new_status, token_info, card_data, project_name, member_id, cron_job_id,
                       *, save_cron_log, apply_stage_action):
    """排程卡片結果處理：寫 CronLog + stage action"""
    output_text = result.get("output", "")
    error_msg = "" if new_status == "completed" else output_text

    with Session(engine) as session:
        from app.models.core import CronJob
        cron_job = session.get(CronJob, cron_job_id)
        cron_job_name = cron_job.name if cron_job else ""

    applied_action = apply_stage_action(idx, new_status)
    save_cron_log(
        cron_job_id=cron_job_id, cron_job_name=cron_job_name,
        card_id=idx.card_id, card_title=idx.title,
        project_id=idx.project_id, project_name=project_name,
        provider=result.get("provider", ""), member_id=member_id,
        status="success" if new_status == "completed" else "error",
        output=output_text, error_message=error_msg,
        prompt_snapshot=card_data.content, token_info=token_info,
        stage_action=applied_action,
    )


def handle_regular_result(idx, result, new_status, card_data, project_path, member_slug,
                          *, update_card_status, apply_stage_action,
                          auto_commit_on_success, auto_shelve_on_failure, parse_and_create_cards):
    """一般卡片結果處理：追加輸出 + stage action + git + create_cards"""
    if result["status"] == "success":
        append_text = f"\n\n---\n\n### AI Output ({result['provider']})\n```\n{result['output'][:1000]}...\n```"
    else:
        append_text = f"\n\n---\n\n### Error ({result['provider']})\n{result['output']}"

    # 檢查卡片是否在執行期間被移走
    with Session(engine) as session:
        current_card = session.get(CardIndex, idx.card_id)
        card_relocated = current_card and (current_card.list_id != idx.list_id or current_card.status == "pending")

    if card_relocated:
        logger.info(f"[Task] Card {idx.card_id}: relocated, skip status update")
        return

    update_card_status(idx.card_id, new_status, append_text)
    apply_stage_action(idx, new_status)

    # 自動 git
    if project_path:
        stage_auto_commit = False
        try:
            with Session(engine) as _s:
                _sl = _s.get(StageList, idx.list_id)
                stage_auto_commit = _sl.auto_commit if _sl else False
        except Exception:
            pass
        if stage_auto_commit:
            if new_status == "completed":
                auto_commit_on_success(project_path, idx.card_id, idx.title, member_slug)
            else:
                auto_shelve_on_failure(project_path, idx.card_id, idx.title, member_slug)

    # 解析 create_cards
    output_text = result.get("output", "")
    if "json:create_cards" in output_text:
        try:
            with Session(engine) as session:
                created_ids = parse_and_create_cards(
                    output_text, idx.project_id, project_path, session,
                    member_slug=member_slug, source_card_id=idx.card_id,
                )
                if created_ids:
                    logger.info(f"[Task] Card {idx.card_id} auto-created {len(created_ids)} cards: {created_ids}")
        except Exception as e:
            logger.warning(f"[Task] Failed to parse create_cards: {e}")


def post_task_hooks(idx, result, new_status, token_info, card_data, project_name,
                    member_id, member_slug, workspace_dir, cron_job_id, **_kwargs):
    """共用後處理 — 委託給 Hook 機制（executor/hooks.py）"""
    from app.core.executor.hooks import TaskContext, run_post_hooks

    ctx = TaskContext(
        card_id=idx.card_id,
        card_title=idx.title,
        project_id=idx.project_id,
        project_name=project_name,
        project_path="",
        member_id=member_id,
        member_slug=member_slug,
        list_id=idx.list_id,
        status=new_status,
        output=result.get("output", ""),
        provider=result.get("provider", ""),
        exit_code=result.get("exit_code", 0),
        token_info=token_info,
        card_content=card_data.content or "",
        workspace_dir=workspace_dir or "",
        cron_job_id=cron_job_id,
    )

    run_post_hooks(ctx)


def _extract_chat_output(raw_output: str) -> str:
    """從 stream-json 原始輸出提取 chat 回應文字"""
    try:
        for line in raw_output.strip().split("\n"):
            line = line.strip()
            if line.startswith("{") and '"subtype":"result"' in line:
                return json.loads(line).get("result", "")
        # fallback: 提取所有 assistant text
        texts = []
        for line in raw_output.strip().split("\n"):
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                d = json.loads(line)
                msg = d.get("message", {})
                for part in (msg.get("content", []) if isinstance(msg.get("content"), list) else []):
                    if isinstance(part, dict) and part.get("type") == "text":
                        texts.append(part["text"])
            except Exception:
                pass
        if texts:
            return "\n".join(texts)
    except Exception:
        pass
    return ""
