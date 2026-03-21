"""
AI Sprite Generator
使用 Gemini API 生成像素風格角色 sprite（16x32 規格，4 方向 x 3 動作）

生成規格：64x128 px，每 4x4 像素為一組 = 等效 16x32 pixel art
合成：36 幀 → 48x384 sprite sheet（Phaser 格式）
"""
import io
from pathlib import Path
from typing import Optional
from PIL import Image
from google import genai
from google.genai import types

# 生成尺寸（4 倍放大）
GEN_W, GEN_H = 64, 128
# 最終尺寸
TARGET_W, TARGET_H = 16, 32
SHEET_COLS, SHEET_ROWS = 3, 12

DIRECTIONS = ["south", "west", "east", "north"]
ACTIONS = ["walk", "sit", "work"]

SPRITE_DIR = Path(__file__).parent.parent.parent / "uploads" / "sprites"
SPRITE_DIR.mkdir(parents=True, exist_ok=True)

# ===== 提示詞 =====

BASE_STYLE = """CRITICAL PIXEL ART RULES:
- Output exactly 64x128 pixels
- Every 4x4 pixel block must be the SAME solid color (simulating 16x32 pixel art at 4x scale)
- LIMITED palette: 8-12 colors max
- NO anti-aliasing, NO gradients, NO smooth transitions between blocks
- Sharp, clean edges at every 4-pixel boundary
- PURE WHITE background (#FFFFFF), no patterns, no checkerboard
- Chibi/SD body proportions: large head, small body, approximately 2 head-heights tall
- Simple clear silhouette, must be readable when shrunk to 16x32"""

DIR_NAMES = {
    "south": "front-facing, looking at the viewer",
    "north": "back-facing, looking away from the viewer",
    "east": "right side profile, facing right",
    "west": "left side profile, facing left",
}

ACTION_FRAMES = {
    "walk": [
        "standing with left foot slightly forward, arms at sides (walk frame 1)",
        "mid-stride, legs apart, arms swinging (walk frame 2)",
        "standing with right foot slightly forward, arms at sides (walk frame 3)",
    ],
    "sit": [
        "sitting on an invisible chair, hands on knees (sit frame 1)",
        "sitting, slight head movement (sit frame 2)",
        "sitting, hands repositioned slightly (sit frame 3)",
    ],
    "work": [
        "sitting at invisible desk, hands forward typing (work frame 1)",
        "sitting, arms slightly moved, typing gesture (work frame 2)",
        "sitting, hands shifted on keyboard (work frame 3)",
    ],
}


def _hero_prompt(desc: str) -> str:
    return f"""Generate a pixel art character sprite.

CHARACTER: {desc}
POSE: Standing idle, front-facing (south direction)

{BASE_STYLE}

Single character on pure white background, 64x128 pixels."""


def _direction_prompt(desc: str, direction: str) -> str:
    return f"""Generate a pixel art character sprite.

CHARACTER: {desc}
DIRECTION: {DIR_NAMES[direction]}

{BASE_STYLE}

Must be the SAME character as the reference image, just viewed from a different angle.
Same outfit, same colors, same proportions.
Single character on pure white background, 64x128 pixels."""


def _anim_prompt(desc: str, direction: str, action: str, frame: int) -> str:
    return f"""Generate a pixel art character sprite animation frame.

CHARACTER: {desc}
DIRECTION: {DIR_NAMES[direction]}
POSE: {ACTION_FRAMES[action][frame]}

{BASE_STYLE}

CONSISTENCY: Must match the reference image exactly - same character, same colors, same outfit.
Only the pose/limbs change for animation.
Single character on pure white background, 64x128 pixels."""


# ===== Gemini 呼叫 =====

def _gen_image(api_key: str, prompt: str, ref: Optional[bytes] = None) -> bytes:
    client = genai.Client(api_key=api_key)
    contents: list = [prompt]
    if ref:
        contents.append(types.Part.from_bytes(data=ref, mime_type="image/png"))

    response = client.models.generate_content(
        model="gemini-2.5-flash-preview-05-20",
        contents=contents,
        config=types.GenerateContentConfig(
            response_modalities=["image", "text"]
        )
    )

    for part in response.candidates[0].content.parts:
        if part.inline_data:
            return part.inline_data.data

    raise ValueError("Gemini returned no image")


def _remove_white_bg(img: Image.Image, threshold: int = 240) -> Image.Image:
    """白底轉透明：接近白色的像素設為 alpha=0"""
    img = img.convert("RGBA")
    pixels = img.load()
    w, h = img.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = pixels[x, y]
            if r >= threshold and g >= threshold and b >= threshold:
                pixels[x, y] = (0, 0, 0, 0)
    return img


def _downscale(data: bytes) -> Image.Image:
    """64x128 → 去白底 → 16x32"""
    img = Image.open(io.BytesIO(data)).convert("RGBA")
    img = _remove_white_bg(img)
    return img.resize((TARGET_W, TARGET_H), Image.NEAREST)


def _member_dir(member_id: int) -> Path:
    d = SPRITE_DIR / str(member_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _save(member_id: int, name: str, data: bytes) -> str:
    d = _member_dir(member_id)
    (d / f"{name}_orig.png").write_bytes(data)
    small = _downscale(data)
    path = d / f"{name}.png"
    small.save(path, "PNG")
    return str(path)


# ===== 公開 API =====

def generate_hero(member_id: int, desc: str, api_key: str) -> dict:
    """Step 1: 主形像（正面）"""
    data = _gen_image(api_key, _hero_prompt(desc))
    path = _save(member_id, "hero_south", data)
    return {"status": "ok", "path": path, "step": "hero_south"}


def generate_direction(member_id: int, desc: str, direction: str, api_key: str) -> dict:
    """Step 2: 特定方向"""
    ref_path = _member_dir(member_id) / "hero_south_orig.png"
    ref = ref_path.read_bytes() if ref_path.exists() else None
    data = _gen_image(api_key, _direction_prompt(desc, direction), ref)
    path = _save(member_id, f"hero_{direction}", data)
    return {"status": "ok", "path": path, "step": f"hero_{direction}"}


def generate_frame(member_id: int, desc: str, direction: str, action: str, frame: int, api_key: str) -> dict:
    """Step 3: 動畫幀"""
    ref_path = _member_dir(member_id) / f"hero_{direction}_orig.png"
    ref = ref_path.read_bytes() if ref_path.exists() else None
    data = _gen_image(api_key, _anim_prompt(desc, direction, action, frame), ref)
    name = f"{action}_{direction}_f{frame}"
    path = _save(member_id, name, data)
    return {"status": "ok", "path": path, "step": name}


def get_progress(member_id: int) -> dict:
    """查詢生成進度"""
    d = _member_dir(member_id)
    frames = {}
    for direction in DIRECTIONS:
        frames[f"hero_{direction}"] = (d / f"hero_{direction}.png").exists()
    for action in ACTIONS:
        for direction in DIRECTIONS:
            for f in range(3):
                frames[f"{action}_{direction}_f{f}"] = (d / f"{action}_{direction}_f{f}.png").exists()
    completed = sum(1 for v in frames.values() if v)
    return {"total": 40, "completed": completed, "frames": frames}


def composite_sheet(member_id: int) -> Optional[str]:
    """Step 4: 合成 48x384 sprite sheet"""
    d = _member_dir(member_id)
    sheet = Image.new("RGBA", (TARGET_W * SHEET_COLS, TARGET_H * SHEET_ROWS), (0, 0, 0, 0))

    row = 0
    for action in ACTIONS:
        for direction in DIRECTIONS:
            for frame in range(3):
                p = d / f"{action}_{direction}_f{frame}.png"
                if p.exists():
                    img = Image.open(p).convert("RGBA")
                    if img.size != (TARGET_W, TARGET_H):
                        img = img.resize((TARGET_W, TARGET_H), Image.NEAREST)
                    sheet.paste(img, (frame * TARGET_W, row * TARGET_H))
            row += 1

    out = d / "sprite_sheet.png"
    sheet.save(out, "PNG")
    return str(out)


def apply_sheet(member_id: int, sprite_index: int) -> Optional[str]:
    """Step 5: 複製到前端 assets"""
    src = _member_dir(member_id) / "sprite_sheet.png"
    if not src.exists():
        return None

    import shutil
    base = Path(__file__).parent.parent.parent
    for subdir in ["frontend/public/assets/office/characters_4dir", "frontend/dist/assets/office/characters_4dir"]:
        target = base / subdir / f"char_{sprite_index}.png"
        if target.parent.exists():
            shutil.copy2(src, target)

    return f"char_{sprite_index}.png"
