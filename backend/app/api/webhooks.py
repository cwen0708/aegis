"""
頻道 Webhook 路由

處理 LINE、WeCom、Feishu 等平台的 Webhook 回調
"""
from fastapi import APIRouter, Request, HTTPException, Header
from fastapi.responses import PlainTextResponse
import logging

from app.channels import channel_manager

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
