"""Sprite Generation API — AI 像素角色生成"""
import base64
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlmodel import Session
from pydantic import BaseModel
from pathlib import Path

from app.database import get_session
from app.models.core import Member, SystemSetting
from app.core.auth import require_admin_token

router = APIRouter(tags=["sprite-gen"])


def _get_gemini_key(session: Session) -> str:
    setting = session.get(SystemSetting, "gemini_api_key")
    if not setting or not setting.value:
        raise HTTPException(400, "Gemini API key not configured (Settings > General)")
    return setting.value


def _get_member(member_id: int, session: Session) -> Member:
    member = session.get(Member, member_id)
    if not member:
        raise HTTPException(404, f"Member {member_id} not found")
    return member


class GenerateRequest(BaseModel):
    description: str = ""


class FrameRequest(BaseModel):
    description: str = ""
    direction: str = "south"
    action: str = "walk"
    frame: int = 0


# ===== 進度查詢 =====

@router.get("/members/{member_id}/sprite/progress")
def sprite_progress(member_id: int, session: Session = Depends(get_session)):
    _get_member(member_id, session)
    from app.core.sprite_generator import get_progress
    return get_progress(member_id)


# ===== 預覽單幀 =====

@router.get("/members/{member_id}/sprite/frame/{name}")
def sprite_frame(member_id: int, name: str):
    from app.core.sprite_generator import SPRITE_DIR
    path = SPRITE_DIR / str(member_id) / f"{name}.png"
    if not path.exists():
        # Try orig
        path = SPRITE_DIR / str(member_id) / f"{name}_orig.png"
    if not path.exists():
        raise HTTPException(404, "Frame not found")
    return FileResponse(path, media_type="image/png")


# ===== 生成步驟 =====

def _load_portrait(member: Member) -> bytes | None:
    """讀取成員的立繪圖片作為角色參考"""
    if not member.portrait:
        return None
    # portrait 路徑類似 /api/v1/portraits/xxx.png
    portrait_dir = Path(__file__).parent.parent.parent / "uploads" / "portraits"
    filename = member.portrait.split("/")[-1]
    portrait_path = portrait_dir / filename
    if portrait_path.exists():
        return portrait_path.read_bytes()
    return None


@router.post("/members/{member_id}/sprite/hero", dependencies=[Depends(require_admin_token)])
def gen_hero(member_id: int, req: GenerateRequest, session: Session = Depends(get_session)):
    member = _get_member(member_id, session)
    api_key = _get_gemini_key(session)
    desc = req.description or f"A cute chibi {member.name}, pixel art game character"
    portrait = _load_portrait(member)

    from app.core.sprite_generator import generate_hero
    return generate_hero(member_id, desc, api_key, portrait=portrait)


@router.post("/members/{member_id}/sprite/direction/{direction}", dependencies=[Depends(require_admin_token)])
def gen_direction(member_id: int, direction: str, req: GenerateRequest, session: Session = Depends(get_session)):
    member = _get_member(member_id, session)
    api_key = _get_gemini_key(session)
    desc = req.description or f"A cute chibi {member.name}, pixel art game character"

    if direction not in ("south", "north", "east", "west"):
        raise HTTPException(400, "direction must be south/north/east/west")

    from app.core.sprite_generator import generate_direction
    return generate_direction(member_id, desc, direction, api_key)


@router.post("/members/{member_id}/sprite/frame", dependencies=[Depends(require_admin_token)])
def gen_frame(member_id: int, req: FrameRequest, session: Session = Depends(get_session)):
    member = _get_member(member_id, session)
    api_key = _get_gemini_key(session)
    desc = req.description or f"A cute chibi {member.name}, pixel art game character"

    if req.direction not in ("south", "north", "east", "west"):
        raise HTTPException(400, "direction must be south/north/east/west")
    if req.action not in ("walk", "sit", "work"):
        raise HTTPException(400, "action must be walk/sit/work")
    if req.frame not in (0, 1, 2):
        raise HTTPException(400, "frame must be 0/1/2")

    from app.core.sprite_generator import generate_frame
    return generate_frame(member_id, desc, req.direction, req.action, req.frame, api_key)


# ===== 批量生成 =====

@router.post("/members/{member_id}/sprite/generate-all", dependencies=[Depends(require_admin_token)])
def gen_all(member_id: int, req: GenerateRequest, session: Session = Depends(get_session)):
    """依序生成所有缺少的幀（同步，可能需要幾分鐘）"""
    member = _get_member(member_id, session)
    api_key = _get_gemini_key(session)
    desc = req.description or f"A cute chibi {member.name}, pixel art game character"

    from app.core.sprite_generator import (
        generate_hero, generate_direction, generate_frame,
        get_progress, DIRECTIONS, ACTIONS
    )

    portrait = _load_portrait(member)
    progress = get_progress(member_id)
    results = []

    # Hero (south)
    if not progress["frames"].get("hero_south"):
        results.append(generate_hero(member_id, desc, api_key, portrait=portrait))

    # Other directions
    for d in DIRECTIONS:
        if d == "south":
            continue
        if not progress["frames"].get(f"hero_{d}"):
            results.append(generate_direction(member_id, desc, d, api_key))

    # Animation frames
    for action in ACTIONS:
        for d in DIRECTIONS:
            for f in range(3):
                key = f"{action}_{d}_f{f}"
                if not progress["frames"].get(key):
                    results.append(generate_frame(member_id, desc, d, action, f, api_key))

    return {"status": "ok", "generated": len(results), "results": results}


# ===== 重置 + 合成 + 套用 =====

@router.delete("/members/{member_id}/sprite/reset", dependencies=[Depends(require_admin_token)])
def reset_sprite(member_id: int, session: Session = Depends(get_session)):
    """清除該成員的所有 sprite 圖片（保留目錄）"""
    _get_member(member_id, session)
    from app.core.sprite_generator import SPRITE_DIR
    d = SPRITE_DIR / str(member_id)
    if d.exists():
        import shutil
        shutil.rmtree(d)
        d.mkdir(parents=True, exist_ok=True)
    return {"ok": True, "message": f"Member {member_id} sprites cleared"}


@router.post("/members/{member_id}/sprite/composite", dependencies=[Depends(require_admin_token)])
def composite(member_id: int, session: Session = Depends(get_session)):
    member = _get_member(member_id, session)
    from app.core.sprite_generator import composite_sheet, TARGET_W
    path = composite_sheet(member_id)
    if not path:
        raise HTTPException(400, "No frames to composite")
    # 更新成員的 sprite_sheet 路徑和 scale
    # 用時間戳重命名避免快取
    import time
    ts = int(time.time())
    sheet_dir = Path(path).parent
    new_name = f"sheet_{ts}.png"
    new_path = sheet_dir / new_name
    Path(path).rename(new_path)
    # 相對於 uploads 的 URL 路徑
    sprite_url = f"/uploads/sprites/{member_id}/{new_name}"
    # scale: 舊版 16px 基準，新版需要縮小
    sprite_scale = 16.0 / TARGET_W  # 128 → 0.125
    member.sprite_sheet = sprite_url
    member.sprite_scale = sprite_scale
    session.add(member)
    session.commit()
    return {"status": "ok", "path": sprite_url, "scale": sprite_scale}


@router.get("/members/{member_id}/sprite/download-raw")
def download_raw_sheet(member_id: int, session: Session = Depends(get_session)):
    """下載原尺寸合併圖（未縮小、未去背，品紅底），供手動編輯"""
    _get_member(member_id, session)
    from app.core.sprite_generator import composite_sheet_raw
    path = composite_sheet_raw(member_id)
    if not path:
        raise HTTPException(400, "No original frames found")
    return FileResponse(path, media_type="image/png", filename=f"sprite_raw_{member_id}.png")


@router.post("/members/{member_id}/sprite/apply", dependencies=[Depends(require_admin_token)])
def apply(member_id: int, session: Session = Depends(get_session)):
    member = _get_member(member_id, session)
    from app.core.sprite_generator import apply_sheet
    result = apply_sheet(member_id, member.sprite_index)
    if not result:
        raise HTTPException(400, "Sprite sheet not found. Composite first.")
    return {"status": "ok", "file": result}
