"""
MediaHook — 解析 AI 輸出中的 <!-- send_file: path --> 標記，透過 channel API 發送檔案

標記格式：
  <!-- send_file: /tmp/user.log/xiao-mu/downloads/12345_DJI_0097.JPG -->
  <!-- send_file: /tmp/user.log/xiao-mu/downloads/12345_report.pdf | 案場巡檢報告 -->
"""
import logging
import re
from app.hooks import Hook, TaskContext

logger = logging.getLogger(__name__)

# 解析 <!-- send_file: path --> 或變體（send_image, sendimage, sendfile 等）
_SEND_FILE_RE = re.compile(
    r'<!--\s*send[_\s]?(?:file|image):\s*(.+?)\s*-->',
    re.IGNORECASE,
)

# 圖片副檔名（用於自動判斷 type）
_IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}


def _infer_platform(chat_id: str) -> str:
    """從 chat_id 格式推斷 platform"""
    if not chat_id:
        return ""
    # Telegram: 純數字（正或負）
    if chat_id.lstrip('-').isdigit():
        return "telegram"
    # LINE: C/U/R 開頭的長字串
    if len(chat_id) > 20 and chat_id[0] in ('C', 'U', 'R'):
        return "line"
    return "telegram"  # 預設


class MediaHook(Hook):
    """POST — 解析 send_file 標記並發送檔案到對話頻道"""

    def on_complete(self, ctx: TaskContext) -> None:
        if not ctx.output:
            return

        # 取得 chat_id（從 TaskContext 或 card_content）
        chat_id = ctx.chat_id
        if not chat_id:
            m = re.search(r'<!-- chat_id: (.+?) -->', ctx.card_content or "")
            if m:
                chat_id = m.group(1)
        if not chat_id:
            return

        platform = _infer_platform(chat_id)
        if not platform:
            return

        # 解析所有 send_file 標記
        matches = _SEND_FILE_RE.findall(ctx.output)
        if not matches:
            return

        from app.core.http_client import InternalAPI

        for raw in matches:
            # 支援 path | caption 格式
            parts = raw.split('|', 1)
            file_path = parts[0].strip()
            caption = parts[1].strip() if len(parts) > 1 else ""

            if not file_path:
                continue

            logger.info(f"[MediaHook] Sending file: {file_path} → {platform}:{chat_id}")
            try:
                InternalAPI.channel_send_file(platform, chat_id, file_path, caption)
            except Exception as e:
                logger.warning(f"[MediaHook] Failed to send {file_path}: {e}")
