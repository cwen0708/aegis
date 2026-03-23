"""Runner Control & Cron Toggle API — 7 endpoints"""
import time
import json as _json
import re as _re
from pathlib import PurePosixPath
from fastapi import APIRouter, Depends
from sqlmodel import Session, select
from typing import Optional, Dict, Tuple
from pydantic import BaseModel
from app.database import get_session
from app.models.core import SystemSetting, CardIndex, Project
import app.core.cron_poller as cron_module

router = APIRouter(tags=["runner"])

# OneStack stream 節流（每張卡片最少間隔 2 秒）
_stream_throttle: Dict[int, float] = {}
_STREAM_INTERVAL = 2.0

# card_id → chat_id 快取（從卡片 content 解析 <!-- chat_id: xxx -->）
_card_chat_id_cache: Dict[int, Optional[str]] = {}

def _get_chat_id_for_card(card_id: int) -> Optional[str]:
    """從卡片 content 取得 chat_id（快取）"""
    if card_id in _card_chat_id_cache:
        return _card_chat_id_cache[card_id]
    try:
        from app.models.core import CardIndex
        from app.database import engine
        from sqlmodel import Session as _S
        with _S(engine) as s:
            idx = s.get(CardIndex, card_id)
            if idx and idx.file_path:
                from pathlib import Path
                fp = Path(idx.file_path)
                if fp.exists():
                    text = fp.read_text(encoding='utf-8')[:500]
                    m = _re.search(r'<!-- chat_id: (.+?) -->', text)
                    if m:
                        _card_chat_id_cache[card_id] = m.group(1)
                        return m.group(1)
    except Exception:
        pass
    _card_chat_id_cache[card_id] = None
    return None

# ===== 工具呼叫翻譯（stream-json → 人話） =====

def _short_path(p: str) -> str:
    """取短路徑（最後 2 層）"""
    parts = PurePosixPath(p).parts
    return "/".join(parts[-2:]) if len(parts) > 2 else p

def _parse_tool_call(line: str) -> Optional[Tuple[str, str]]:
    """嘗試從 stream-json 行解析工具呼叫，回傳 (event_type, 人話摘要)
    回傳 None 表示不是工具呼叫或不值得顯示"""
    try:
        data = _json.loads(line)
    except (ValueError, TypeError):
        return None

    # Claude stream-json 格式
    msg = data.get("message", {}) if isinstance(data, dict) else {}
    if not msg:
        msg = data

    # 找 content 裡的 tool_use
    content = msg.get("content", [])
    if isinstance(content, str):
        return None
    if not isinstance(content, list):
        return None

    for part in content:
        if not isinstance(part, dict):
            continue
        ptype = part.get("type", "")

        if ptype == "tool_use":
            tool = part.get("name", "")
            inp = part.get("input", {})
            return _translate_tool(tool, inp)

        if ptype == "text":
            text = part.get("text", "").strip()
            if text and len(text) < 200:
                return ("output", f"💬 {text[:100]}")

        if ptype == "thinking":
            return ("output", "💭 思考中...")

    return None

def _translate_tool(tool: str, inp: dict) -> Tuple[str, str]:
    """將工具名稱和參數翻譯成人話"""
    if tool == "Read":
        fp = inp.get("file_path", "")
        return ("tool_call", f"📖 讀取 {_short_path(fp)}")
    elif tool == "Edit":
        fp = inp.get("file_path", "")
        return ("tool_call", f"✏️ 修改 {_short_path(fp)}")
    elif tool == "Write":
        fp = inp.get("file_path", "")
        return ("tool_call", f"📝 建立 {_short_path(fp)}")
    elif tool == "Bash":
        cmd = inp.get("command", "")[:60]
        desc = inp.get("description", "")
        label = desc[:40] if desc else cmd
        return ("tool_call", f"💻 {label}")
    elif tool == "Grep":
        pattern = inp.get("pattern", "")
        return ("tool_call", f"🔍 搜尋 {pattern[:40]}")
    elif tool == "Glob":
        pattern = inp.get("pattern", "")
        return ("tool_call", f"📁 搜尋檔案 {pattern[:40]}")
    elif tool == "WebFetch":
        url = inp.get("url", "")[:60]
        return ("tool_call", f"🌐 取得 {url}")
    elif tool == "WebSearch":
        query = inp.get("query", "")[:40]
        return ("tool_call", f"🔎 搜尋 {query}")
    elif tool == "Agent":
        desc = inp.get("description", "子代理")[:40]
        return ("tool_call", f"🤖 {desc}")
    elif tool == "Skill":
        skill = inp.get("skill", "")
        return ("tool_call", f"⚡ 技能 {skill}")
    elif tool == "TodoWrite":
        return None  # 不顯示
    else:
        return ("tool_call", f"🔧 {tool}")


# ==========================================
# Runner Control (DB-based for Worker process)
# ==========================================
@router.post("/runner/pause")
def pause_runner(session: Session = Depends(get_session)):
    """暫停 Worker（透過 DB 旗標）"""
    setting = session.get(SystemSetting, "worker_paused")
    if setting:
        setting.value = "true"
    else:
        setting = SystemSetting(key="worker_paused", value="true")
        session.add(setting)
    session.commit()
    return {"ok": True, "is_paused": True}


@router.post("/runner/resume")
def resume_runner(session: Session = Depends(get_session)):
    """恢復 Worker（透過 DB 旗標）"""
    setting = session.get(SystemSetting, "worker_paused")
    if setting:
        setting.value = "false"
    else:
        setting = SystemSetting(key="worker_paused", value="false")
        session.add(setting)
    session.commit()
    return {"ok": True, "is_paused": False}


@router.get("/runner/status")
def runner_status(session: Session = Depends(get_session)):
    """從 DB 查詢運行中任務（Worker 獨立程序架構）"""
    from sqlmodel import select

    stmt = select(CardIndex).where(CardIndex.status == "running")
    running_cards = list(session.exec(stmt).all())

    tasks_data = []
    for idx in running_cards:
        project = session.get(Project, idx.project_id)
        tasks_data.append({
            "task_id": idx.card_id,
            "project": project.name if project else "",
            "card_title": idx.title,
            "started_at": idx.updated_at.timestamp() if idx.updated_at else 0,
            "pid": None,  # Worker 獨立程序
            "provider": "",
            "member_id": idx.member_id,
        })

    # 讀取最大工作台數
    max_ws_setting = session.get(SystemSetting, "max_workstations")
    max_workstations = int(max_ws_setting.value) if max_ws_setting else 3

    # 讀取暫停旗標
    paused_setting = session.get(SystemSetting, "worker_paused")
    is_paused = paused_setting and paused_setting.value == "true"

    # 讀取版本號
    version_setting = session.get(SystemSetting, "app_version")
    app_version = version_setting.value if version_setting else "unknown"

    return {
        "is_paused": is_paused,
        "running_tasks": tasks_data,
        "workstations_used": len(tasks_data),
        "workstations_total": max_workstations,
        "version": app_version,
    }


# ==========================================
# Internal APIs (for Worker process)
# ==========================================
class BroadcastLogRequest(BaseModel):
    card_id: int
    line: str

class BroadcastEventRequest(BaseModel):
    event: str
    payload: dict

@router.post("/internal/broadcast-log")
async def internal_broadcast_log(req: BroadcastLogRequest):
    """Worker 呼叫：廣播任務輸出行 → WebSocket + OneStack stream"""
    from app.core.ws_manager import broadcast_event
    await broadcast_event("task_log", {"card_id": req.card_id, "line": req.line})

    # 解析工具呼叫 → 人話，轉發到 OneStack aegis_stream（節流 2 秒）
    try:
        from app.core.onestack_connector import connector
        if connector.enabled:
            parsed = _parse_tool_call(req.line)
            if parsed:
                event_type, summary = parsed
                now = time.time()
                last = _stream_throttle.get(req.card_id, 0)
                if now - last >= _STREAM_INTERVAL:
                    _stream_throttle[req.card_id] = now
                    chat_id = _get_chat_id_for_card(req.card_id)
                    await connector.stream_event(req.card_id, event_type, summary, chat_id=chat_id)
    except Exception:
        pass

    return {"ok": True}


@router.post("/internal/broadcast-event")
async def internal_broadcast_event(req: BroadcastEventRequest):
    """Worker 呼叫：廣播事件 → WebSocket + OneStack stream"""
    from app.core.ws_manager import broadcast_event
    await broadcast_event(req.event, req.payload)

    # 轉發任務狀態到 OneStack（不節流，重要事件）
    try:
        from app.core.onestack_connector import connector
        if connector.enabled:
            card_id = req.payload.get("card_id")
            if card_id and req.event in ("task_started", "task_completed", "task_failed"):
                event_type = "status" if req.event == "task_started" else "result" if req.event == "task_completed" else "error"
                content = req.payload.get("status", req.event)
                chat_id = _get_chat_id_for_card(card_id)
                await connector.stream_event(card_id, event_type, str(content), chat_id=chat_id)
                # 清理快取
                _stream_throttle.pop(card_id, None)
                if req.event in ("task_completed", "task_failed"):
                    _card_chat_id_cache.pop(card_id, None)
    except Exception:
        pass

    return {"ok": True}


# ==========================================
# Channel Send（AI 即時回應用）
# ==========================================
class ChannelSendRequest(BaseModel):
    platform: str
    chat_id: str
    text: str
    edit_message_id: Optional[str] = None

@router.post("/internal/channel-send")
async def internal_channel_send(req: ChannelSendRequest):
    """AI runner 呼叫：透過 channel 發送/編輯訊息"""
    from app.channels.manager import channel_manager
    from app.channels.bus import OutboundMessage

    channel = channel_manager.get_channel(req.platform)
    if not channel:
        return {"ok": False, "error": f"Channel {req.platform} not found"}

    msg = OutboundMessage(
        chat_id=req.chat_id,
        platform=req.platform,
        text=req.text,
        edit_message_id=req.edit_message_id or None,
    )
    message_id = await channel.send(msg)
    return {"ok": True, "message_id": message_id}


# ==========================================
# Cron Toggle
# ==========================================
class CronToggleRequest(BaseModel):
    project_id: int


@router.post("/cron/pause")
def pause_cron(body: CronToggleRequest):
    cron_module.paused_projects.add(body.project_id)
    return {"ok": True, "paused_projects": list(cron_module.paused_projects)}


@router.post("/cron/resume")
def resume_cron(body: CronToggleRequest):
    cron_module.paused_projects.discard(body.project_id)
    return {"ok": True, "paused_projects": list(cron_module.paused_projects)}
