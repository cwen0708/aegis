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
# 最終尺寸（128x256，pixel art 以 8x8 色塊呈現）
TARGET_W, TARGET_H = 128, 256
SHEET_COLS, SHEET_ROWS = 3, 12

DIRECTIONS = ["south", "west", "east", "north"]
ACTIONS = ["walk", "sit", "work"]

SPRITE_DIR = Path(__file__).parent.parent.parent / "uploads" / "sprites"
SPRITE_DIR.mkdir(parents=True, exist_ok=True)

# ===== 提示詞 =====

CHROMA_KEY = (255, 0, 255)  # #FF00FF 品紅色，去背用

BASE_STYLE = """CRITICAL PIXEL ART RULES:
- Output exactly 64x128 pixels
- Every 4x4 pixel block must be the SAME solid color (simulating 16x32 pixel art at 4x scale)
- LIMITED palette: 8-12 colors max
- NO anti-aliasing, NO gradients, NO smooth transitions between blocks
- Sharp, clean edges at every 4-pixel boundary
- Background MUST be solid MAGENTA (#FF00FF) — fill ALL empty space with this exact color
- Do NOT use magenta (#FF00FF) anywhere on the character itself
- BODY PROPORTIONS: Head-to-body ratio MUST be exactly 1:2.5 (head is ~18px tall, full body is ~45px tall in the 64x128 canvas). Chibi/SD style with large head.
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


def _hero_prompt(desc: str, has_portrait: bool = False) -> str:
    ref_note = """
REFERENCE: A character portrait/illustration is attached.
Use it as visual reference for the character's appearance (hair, outfit, colors).
Convert the style to pixel art while preserving key visual features.""" if has_portrait else ""
    return f"""Generate a pixel art character sprite.

CHARACTER: {desc}
POSE: Standing idle, front-facing (south direction)
{ref_note}

{BASE_STYLE}

Single character on solid MAGENTA (#FF00FF) background, 64x128 pixels."""


def _direction_prompt(desc: str, direction: str) -> str:
    return f"""Generate a pixel art character sprite.

CHARACTER: {desc}
DIRECTION: {DIR_NAMES[direction]}

{BASE_STYLE}

Must be the SAME character as the reference image, just viewed from a different angle.
Same outfit, same colors, same proportions.
Single character on solid MAGENTA (#FF00FF) background, 64x128 pixels."""


def _anim_prompt(desc: str, direction: str, action: str, frame: int) -> str:
    return f"""Generate a pixel art character sprite animation frame.

CHARACTER: {desc}
DIRECTION: {DIR_NAMES[direction]}
POSE: {ACTION_FRAMES[action][frame]}

{BASE_STYLE}

CONSISTENCY: Must match the reference image exactly - same character, same colors, same outfit.
Only the pose/limbs change for animation.
IMPORTANT: Draw ONLY ONE character. No duplicates, no multiple figures.
Single character on solid MAGENTA (#FF00FF) background, 64x128 pixels."""


# ===== Gemini 呼叫 =====

def _gen_image(api_key: str, prompt: str, ref: Optional[bytes] = None, portrait: Optional[bytes] = None) -> bytes:
    client = genai.Client(api_key=api_key)
    contents: list = [prompt]
    if portrait:
        contents.append(types.Part.from_bytes(data=portrait, mime_type="image/png"))
    if ref:
        contents.append(types.Part.from_bytes(data=ref, mime_type="image/png"))

    response = client.models.generate_content(
        model="gemini-3.1-flash-image-preview",
        contents=contents,
        config=types.GenerateContentConfig(
            response_modalities=["image", "text"]
        )
    )

    for part in response.candidates[0].content.parts:
        if part.inline_data:
            return part.inline_data.data

    raise ValueError("Gemini returned no image")


def _remove_chroma_bg(img: Image.Image, tolerance: int = 30) -> Image.Image:
    """品紅底（#FF00FF）轉透明：接近品紅色的像素設為 alpha=0
    同時也處理白底（向下相容舊圖）"""
    img = img.convert("RGBA")
    pixels = img.load()
    w, h = img.size
    cr, cg, cb = CHROMA_KEY
    for y in range(h):
        for x in range(w):
            r, g, b, a = pixels[x, y]
            # 品紅色去背
            if abs(r - cr) <= tolerance and g <= tolerance and abs(b - cb) <= tolerance:
                pixels[x, y] = (0, 0, 0, 0)
            # 白底去背（向下相容）
            elif r >= 240 and g >= 240 and b >= 240:
                pixels[x, y] = (0, 0, 0, 0)
    return img


def _quantize_to_grid(img: Image.Image, grid: int = 4) -> Image.Image:
    """將圖片量化為 grid x grid 的色塊（每個色塊取最常見的顏色）
    確保縮放後不會產生混色/模糊的半透明像素"""
    w, h = img.size
    target_w = w // grid
    target_h = h // grid
    result = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
    pixels = img.load()
    result_pixels = result.load()

    for ty in range(target_h):
        for tx in range(target_w):
            # 取 grid x grid 區塊內的所有像素
            colors = {}
            for dy in range(grid):
                for dx in range(grid):
                    sx = tx * grid + dx
                    sy = ty * grid + dy
                    if sx < w and sy < h:
                        c = pixels[sx, sy]
                        colors[c] = colors.get(c, 0) + 1
            # 選最常見的顏色（多數決）
            if colors:
                result_pixels[tx, ty] = max(colors, key=colors.get)

    return result


def _downscale(data: bytes) -> Image.Image:
    """任意尺寸 → 去白底 → 量化到 16x32（無模糊）

    流程：
    1. 去白底
    2. 先用 NEAREST 縮到精確的整數倍尺寸（如 64x128 = 4倍）
    3. 再用 grid 量化取多數決顏色
    這樣每個 grid 格子都是精確的 NxN，不會跨邊界
    """
    img = Image.open(io.BytesIO(data)).convert("RGBA")
    img = _remove_chroma_bg(img)

    w, h = img.size
    if w == TARGET_W and h == TARGET_H:
        return img

    # 決定中繼倍率（盡量接近原圖大小，但必須是整數倍）
    # 例如 720x1456 → scale_w=45, scale_h=45.5 → 取 45 → 中繼 720x1440
    scale = min(w // TARGET_W, h // TARGET_H)
    grid = max(scale, 1)

    # 先 NEAREST 縮到精確的 grid 倍尺寸，去掉多餘像素
    intermediate_w = TARGET_W * grid
    intermediate_h = TARGET_H * grid
    if (w, h) != (intermediate_w, intermediate_h):
        img = img.resize((intermediate_w, intermediate_h), Image.NEAREST)

    # grid 量化：每個 grid x grid 色塊取多數決
    return _quantize_to_grid(img, grid)


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

def generate_hero(member_id: int, desc: str, api_key: str, portrait: Optional[bytes] = None) -> dict:
    """Step 1: 主形像（正面），可傳入立繪作為角色參考"""
    data = _gen_image(api_key, _hero_prompt(desc, has_portrait=portrait is not None), portrait=portrait)
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
    """Step 5: 複製到前端 assets，使用 member_char_{member_id}.png 不覆蓋預設"""
    src = _member_dir(member_id) / "sprite_sheet.png"
    if not src.exists():
        return None

    import shutil
    filename = f"member_char_{member_id}.png"
    project_root = Path(__file__).parent.parent.parent.parent
    copied = False
    for subdir in ["frontend/public/assets/office/characters_4dir", "frontend/dist/assets/office/characters_4dir"]:
        target = project_root / subdir / filename
        if target.parent.exists():
            shutil.copy2(src, target)
            copied = True
    if not copied:
        return None

    return filename
