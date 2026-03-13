"""
AI Portrait Generator
使用 Gemini API 生成 AVG 風格立繪，並自動去背
"""
import io
import base64
from typing import Optional
from google import genai
from google.genai import types
from rembg import remove
from PIL import Image


def analyze_photo(photo_bytes: bytes, name: str, api_key: str) -> str:
    """
    使用 Gemini Flash 分析照片特徵
    """
    client = genai.Client(api_key=api_key)

    prompt = f"""分析照片中的人物，提取可用於繪製動漫角色的視覺特徵：

提取項目：
- 性別、年齡段
- 髮型、髮色（精確描述長度、造型、顏色）
- 臉型、膚色
- 眼型、眼色
- 眼鏡（有/無，框型）
- 明顯臉部特徵（酒窩、痣等）
- 服裝風格

以「{name}」為角色名，用英文寫出 4-5 句精確的外觀描述。
描述要精確到可以據此畫出保留本人特徵的動漫角色。
只輸出描述，不要 JSON 或其他格式。"""

    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=[
            prompt,
            types.Part.from_bytes(data=photo_bytes, mime_type="image/jpeg")
        ]
    )

    return response.text.strip()


def generate_portrait(photo_bytes: bytes, description: str, api_key: str) -> bytes:
    """
    使用 Gemini Imagen 生成 AVG 風格立繪
    """
    client = genai.Client(api_key=api_key)

    prompt = f"""Generate a visual novel (AVG/galgame) style character portrait.

CHARACTER FEATURES (must match the reference photo):
{description}

STYLE REQUIREMENTS:
- Japanese visual novel / galgame art style
- Clean cel-shading with soft gradients
- Large expressive eyes (anime style)
- Detailed hair with highlights and flow
- Professional office attire or smart casual
- Gentle, friendly expression
- Upper body portrait (bust shot), facing slightly to the side

TECHNICAL REQUIREMENTS:
- Pure solid white background (#FFFFFF) for easy removal
- High resolution, clean linework
- Soft ambient lighting
- Single character only

CRITICAL:
- PRESERVE the person's unique facial features from the reference photo
- Keep the same hairstyle, hair color, and face shape
- Match any glasses or accessories
- The character should be clearly recognizable as the same person
- Style similar to: Clannad, Steins;Gate, or modern visual novels"""

    response = client.models.generate_content(
        model="gemini-3.1-flash-image-preview",
        contents=[
            prompt,
            types.Part.from_bytes(data=photo_bytes, mime_type="image/jpeg")
        ],
        config=types.GenerateContentConfig(
            response_modalities=["image", "text"]
        )
    )

    # 從回應中提取圖片
    for part in response.candidates[0].content.parts:
        if part.inline_data:
            return part.inline_data.data

    raise ValueError("No image generated in response")


def remove_background(image_bytes: bytes) -> bytes:
    """
    使用 rembg 去背，輸出透明 PNG
    """
    # rembg 直接處理
    output = remove(image_bytes)

    # 確保是 PNG 格式
    img = Image.open(io.BytesIO(output))
    if img.mode != 'RGBA':
        img = img.convert('RGBA')

    buffer = io.BytesIO()
    img.save(buffer, format='PNG', optimize=True)
    return buffer.getvalue()


def generate_member_portrait(photo_bytes: bytes, name: str, api_key: str) -> tuple[bytes, str]:
    """
    完整流程：分析照片 → 生成立繪 → 去背

    Returns:
        (png_bytes, description)
    """
    # Step 1: 分析照片特徵
    description = analyze_photo(photo_bytes, name, api_key)
    print(f"[portrait] Analyzed features: {description[:100]}...")

    # Step 2: 生成立繪
    portrait_bytes = generate_portrait(photo_bytes, description, api_key)
    print(f"[portrait] Generated image: {len(portrait_bytes)} bytes")

    # Step 3: 去背
    png_bytes = remove_background(portrait_bytes)
    print(f"[portrait] Background removed: {len(png_bytes)} bytes")

    return png_bytes, description
