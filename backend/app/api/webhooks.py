"""
頻道 Webhook 路由

處理 LINE、WeCom、Feishu 等平台的 Webhook 回調，
以及用戶自定義 Webhook 的 CRUD 管理。
"""
from fastapi import APIRouter, Request, HTTPException, Header, Depends
from fastapi.responses import PlainTextResponse
from sqlmodel import Session, select
from pydantic import BaseModel, HttpUrl
from typing import Optional, List
from datetime import datetime, timezone
import logging

from app.channels import channel_manager
from app.database import get_session
from app.models.core import WebhookConfig, Project, PersonProject, BotUser
from app.core.auth import verify_session_token, decode_session_token

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


# ==========================================
# LINE Webhook
# ==========================================
@router.post("/line")
async def line_webhook(
    request: Request,
    x_line_signature: str = Header(..., alias="X-Line-Signature"),
):
    """
    LINE Messaging API Webhook

    需要在 LINE Developers Console 設定 Webhook URL:
    https://your-domain.com/api/v1/webhooks/line
    """
    from app.channels.adapters.line import LineChannel

    # 找到已註冊的 LINE 頻道
    line_channel = None
    for ch in channel_manager._channels:
        if isinstance(ch, LineChannel):
            line_channel = ch
            break

    if not line_channel:
        logger.warning("[Webhook] LINE channel not registered")
        raise HTTPException(status_code=503, detail="LINE channel not configured")

    body = await request.body()
    body_str = body.decode("utf-8")

    try:
        count = await line_channel.handle_webhook(body_str, x_line_signature)
        logger.info(f"[Webhook] LINE: processed {count} events")
        return {"status": "ok", "events": count}
    except Exception as e:
        logger.error(f"[Webhook] LINE error: {e}")
        raise HTTPException(status_code=400, detail=str(e))


# ==========================================
# WeCom (企業微信) Webhook
# ==========================================
@router.get("/wecom")
async def wecom_verify(
    msg_signature: str,
    timestamp: str,
    nonce: str,
    echostr: str,
):
    """
    企業微信 URL 驗證（GET 請求）

    配置回調時會發送此請求驗證 URL
    """
    from app.channels.adapters.wecom import WeComChannel

    wecom_channel = None
    for ch in channel_manager._channels:
        if isinstance(ch, WeComChannel):
            wecom_channel = ch
            break

    if not wecom_channel:
        raise HTTPException(status_code=503, detail="WeCom channel not configured")

    if not WeComChannel.verify_signature(wecom_channel.token, timestamp, nonce, msg_signature):
        logger.warning("[Webhook] WeCom signature verification failed")
        raise HTTPException(status_code=403, detail="Invalid signature")

    return PlainTextResponse(content=echostr)


@router.post("/wecom")
async def wecom_webhook(
    request: Request,
    msg_signature: str,
    timestamp: str,
    nonce: str,
):
    """
    企業微信訊息回調（POST 請求）

    需要在企業微信管理後台設定接收訊息 URL:
    https://your-domain.com/api/v1/webhooks/wecom
    """
    from app.channels.adapters.wecom import WeComChannel

    wecom_channel = None
    for ch in channel_manager._channels:
        if isinstance(ch, WeComChannel):
            wecom_channel = ch
            break

    if not wecom_channel:
        logger.warning("[Webhook] WeCom channel not registered")
        raise HTTPException(status_code=503, detail="WeCom channel not configured")

    body = await request.body()
    body_str = body.decode("utf-8")

    try:
        count = await wecom_channel.handle_webhook(msg_signature, timestamp, nonce, body_str)
        logger.info(f"[Webhook] WeCom: processed {count} events")
        return PlainTextResponse(content="success")
    except Exception as e:
        logger.error(f"[Webhook] WeCom error: {e}")
        return PlainTextResponse(content="success")  # 企業微信要求返回 success


# ==========================================
# Feishu (飛書/Lark) Webhook
# ==========================================
@router.post("/feishu")
async def feishu_webhook(request: Request):
    """
    飛書/Lark 事件訂閱 Webhook

    需要在飛書開放平台設定事件訂閱 URL:
    https://your-domain.com/api/v1/webhooks/feishu
    """
    from app.channels.adapters.feishu import FeishuChannel

    feishu_channel = None
    for ch in channel_manager._channels:
        if isinstance(ch, FeishuChannel):
            feishu_channel = ch
            break

    if not feishu_channel:
        logger.warning("[Webhook] Feishu channel not registered")
        raise HTTPException(status_code=503, detail="Feishu channel not configured")

    body = await request.json()

    try:
        result = await feishu_channel.handle_webhook(body)
        return result  # 可能是 challenge 回應或空 dict
    except Exception as e:
        logger.error(f"[Webhook] Feishu error: {e}")
        raise HTTPException(status_code=400, detail=str(e))


# ==========================================
# Health Check
# ==========================================
@router.get("/health")
async def webhooks_health():
    """Webhook 端點健康檢查"""
    statuses = await channel_manager.health_check_all()
    return {
        "status": "ok",
        "channels": [
            {
                "platform": s.platform,
                "connected": s.is_connected,
                "error": s.error,
            }
            for s in statuses
        ],
    }


# ==========================================
# 用戶自定義 Webhook CRUD
# ==========================================

class WebhookCreate(BaseModel):
    project_id: int
    name: str
    url: str
    active: bool = True


class WebhookUpdate(BaseModel):
    name: Optional[str] = None
    url: Optional[str] = None
    active: Optional[bool] = None


class WebhookResponse(BaseModel):
    id: int
    project_id: int
    name: str
    url: str
    active: bool
    created_at: datetime
    updated_at: datetime


def _require_project_access(request: Request, project_id: int, session: Session):
    """驗證請求者是否有該專案的存取權限（admin token 或 PersonProject 成員）"""
    auth_header = request.headers.get("authorization", "")
    token = auth_header[7:] if auth_header.startswith("Bearer ") else ""

    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")

    payload = decode_session_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")

    # admin token → 無限制
    if payload.get("type") == "admin":
        return

    # user token → 檢查 PersonProject
    uid = payload.get("uid")
    if not uid:
        raise HTTPException(status_code=403, detail="Permission denied")

    user = session.get(BotUser, uid)
    if not user or not user.person_id:
        raise HTTPException(status_code=403, detail="Permission denied")

    membership = session.exec(
        select(PersonProject).where(
            PersonProject.person_id == user.person_id,
            PersonProject.project_id == project_id,
            PersonProject.can_view == True,
        )
    ).first()
    if not membership:
        raise HTTPException(status_code=403, detail="No access to this project")


@router.post("/custom", response_model=WebhookResponse)
def create_custom_webhook(
    body: WebhookCreate,
    request: Request,
    session: Session = Depends(get_session),
):
    """建立自定義 Webhook"""
    _require_project_access(request, body.project_id, session)

    if not body.name.strip():
        raise HTTPException(status_code=422, detail="name is required")
    if not body.url.startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="url must be a valid HTTP/HTTPS URL")

    # 同一專案內名稱唯一
    existing = session.exec(
        select(WebhookConfig).where(
            WebhookConfig.project_id == body.project_id,
            WebhookConfig.name == body.name,
        )
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Webhook name already exists in this project")

    project = session.get(Project, body.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    wh = WebhookConfig(
        project_id=body.project_id,
        name=body.name.strip(),
        url=body.url,
        active=body.active,
    )
    session.add(wh)
    session.commit()
    session.refresh(wh)
    return WebhookResponse(
        id=wh.id,
        project_id=wh.project_id,
        name=wh.name,
        url=wh.url,
        active=wh.active,
        created_at=wh.created_at,
        updated_at=wh.updated_at,
    )


@router.get("/custom", response_model=List[WebhookResponse])
def list_custom_webhooks(
    project_id: int,
    request: Request,
    session: Session = Depends(get_session),
):
    """列出專案下所有自定義 Webhook"""
    _require_project_access(request, project_id, session)

    items = session.exec(
        select(WebhookConfig).where(WebhookConfig.project_id == project_id)
    ).all()
    return [
        WebhookResponse(
            id=w.id,
            project_id=w.project_id,
            name=w.name,
            url=w.url,
            active=w.active,
            created_at=w.created_at,
            updated_at=w.updated_at,
        )
        for w in items
    ]


@router.get("/custom/{webhook_id}", response_model=WebhookResponse)
def get_custom_webhook(
    webhook_id: int,
    request: Request,
    session: Session = Depends(get_session),
):
    """查詢單個自定義 Webhook"""
    wh = session.get(WebhookConfig, webhook_id)
    if not wh:
        raise HTTPException(status_code=404, detail="Webhook not found")

    _require_project_access(request, wh.project_id, session)

    return WebhookResponse(
        id=wh.id,
        project_id=wh.project_id,
        name=wh.name,
        url=wh.url,
        active=wh.active,
        created_at=wh.created_at,
        updated_at=wh.updated_at,
    )


@router.put("/custom/{webhook_id}", response_model=WebhookResponse)
def update_custom_webhook(
    webhook_id: int,
    body: WebhookUpdate,
    request: Request,
    session: Session = Depends(get_session),
):
    """更新自定義 Webhook"""
    wh = session.get(WebhookConfig, webhook_id)
    if not wh:
        raise HTTPException(status_code=404, detail="Webhook not found")

    _require_project_access(request, wh.project_id, session)

    if body.name is not None:
        if not body.name.strip():
            raise HTTPException(status_code=422, detail="name cannot be empty")
        # 名稱衝突檢查（排除自身）
        conflict = session.exec(
            select(WebhookConfig).where(
                WebhookConfig.project_id == wh.project_id,
                WebhookConfig.name == body.name,
                WebhookConfig.id != webhook_id,
            )
        ).first()
        if conflict:
            raise HTTPException(status_code=409, detail="Webhook name already exists in this project")
        wh.name = body.name.strip()

    if body.url is not None:
        if not body.url.startswith(("http://", "https://")):
            raise HTTPException(status_code=422, detail="url must be a valid HTTP/HTTPS URL")
        wh.url = body.url

    if body.active is not None:
        wh.active = body.active

    wh.updated_at = datetime.now(timezone.utc)
    session.add(wh)
    session.commit()
    session.refresh(wh)
    return WebhookResponse(
        id=wh.id,
        project_id=wh.project_id,
        name=wh.name,
        url=wh.url,
        active=wh.active,
        created_at=wh.created_at,
        updated_at=wh.updated_at,
    )


@router.delete("/custom/{webhook_id}")
def delete_custom_webhook(
    webhook_id: int,
    request: Request,
    session: Session = Depends(get_session),
):
    """刪除自定義 Webhook"""
    wh = session.get(WebhookConfig, webhook_id)
    if not wh:
        raise HTTPException(status_code=404, detail="Webhook not found")

    _require_project_access(request, wh.project_id, session)

    session.delete(wh)
    session.commit()
    return {"status": "deleted", "id": webhook_id}
