"""頻道設定 API — 4 endpoints"""
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session
from app.database import get_session
from app.models.core import SystemSetting
import json as json_module

router = APIRouter(tags=["channels"])

CHANNEL_DEFAULTS = {
    "telegram": {"enabled": False, "bot_token": ""},
    "line": {"enabled": False, "channel_secret": "", "access_token": ""},
    "discord": {"enabled": False, "bot_token": ""},
    "slack": {"enabled": False, "bot_token": "", "app_token": ""},
    "wecom": {"enabled": False, "corp_id": "", "corp_secret": "", "agent_id": ""},
    "feishu": {"enabled": False, "app_id": "", "app_secret": "", "is_lark": False},
}


@router.get("/channels")
def get_channel_configs(session: Session = Depends(get_session)):
    """取得所有頻道設定"""
    result = {}
    for channel_name, defaults in CHANNEL_DEFAULTS.items():
        key = f"channel_{channel_name}"
        setting = session.get(SystemSetting, key)
        if setting:
            try:
                config = json_module.loads(setting.value)
                result[channel_name] = {**defaults, **config}
            except:
                result[channel_name] = dict(defaults)
        else:
            result[channel_name] = dict(defaults)
    return result


@router.put("/channels/{channel_name}")
def update_channel_config(
    channel_name: str,
    config: dict,
    session: Session = Depends(get_session)
):
    """更新單一頻道設定"""
    if channel_name not in CHANNEL_DEFAULTS:
        raise HTTPException(status_code=400, detail=f"Unknown channel: {channel_name}")

    key = f"channel_{channel_name}"
    existing = session.get(SystemSetting, key)
    config_json = json_module.dumps(config, ensure_ascii=False)

    if existing:
        existing.value = config_json
        session.add(existing)
    else:
        session.add(SystemSetting(key=key, value=config_json))
    session.commit()

    return {"status": "ok", "channel": channel_name, "config": config}


@router.get("/channels/status")
async def get_channel_status():
    """取得所有頻道的即時狀態"""
    from app.channels import channel_manager
    statuses = await channel_manager.health_check_all()
    return {
        "channels": [
            {
                "platform": s.platform,
                "connected": s.is_connected,
                "error": s.error,
                "last_heartbeat": s.last_heartbeat.isoformat() if s.last_heartbeat else None,
                "stats": s.stats,
            }
            for s in statuses.values()
        ]
    }


@router.post("/channels/restart")
async def restart_channels():
    """重啟所有頻道（套用新設定）"""
    from app.channels import channel_manager
    try:
        count = await channel_manager.restart_all()
        return {"status": "ok", "message": f"已重啟 {count} 個頻道", "active_channels": count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
