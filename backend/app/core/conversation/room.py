"""
ConversationRoom — 一場會議的狀態管理

負責：
- 會議紀錄檔案的建立和追加
- 共用歷史的維護
- 參與成員列表
"""
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_INSTALL_ROOT = Path(__file__).resolve().parent.parent.parent.parent
MEETINGS_DIR = _INSTALL_ROOT / ".aegis" / "meetings"


class ConversationRoom:
    """一場會議的狀態。"""

    def __init__(
        self,
        meeting_id: str,
        title: str = "",
        participants: list[str] = None,  # member slugs
    ):
        self.meeting_id = meeting_id
        self.title = title
        self.participants = participants or []
        self.history: list[dict] = []  # [{speaker, slug, content}]
        self.file_path = MEETINGS_DIR / f"{meeting_id}.md"

    def create_file(self, opening: str = "") -> Path:
        """建立會議紀錄檔案。"""
        MEETINGS_DIR.mkdir(parents=True, exist_ok=True)

        tz = timezone(timedelta(hours=8))
        now = datetime.now(tz).strftime("%Y-%m-%d %H:%M")

        lines = [
            f"# {self.title or self.meeting_id}",
            f"日期：{now}",
            f"參與者：{', '.join(self.participants)}",
            "",
        ]
        if opening:
            lines.append(opening)
            lines.append("")

        self.file_path.write_text("\n".join(lines), encoding="utf-8")
        logger.info(f"[Meeting] Created {self.file_path}")
        return self.file_path

    def append(self, speaker_name: str, speaker_slug: str, content: str) -> None:
        """追加一段發言到歷史和檔案。"""
        self.history.append({
            "speaker": speaker_name,
            "slug": speaker_slug,
            "content": content,
        })

        # 追加到檔案
        block = f"\n## [{speaker_name}]\n\n{content.strip()}\n"
        with open(self.file_path, "a", encoding="utf-8") as f:
            f.write(block)

    def get_history_text(self) -> str:
        """取得格式化的對話歷史（用於 prompt）。"""
        lines = []
        for entry in self.history:
            lines.append(f"[{entry['speaker']}] {entry['content']}")
        return "\n\n".join(lines)

    def get_prompt_for(self, member_name: str, instruction: str = "") -> str:
        """組裝給某成員的發言 prompt。"""
        history = self.get_history_text()

        prompt = f"以下是目前的會議紀錄：\n\n{history}"
        prompt += f"\n\n---\n現在輪到你（{member_name}）發言。"
        if instruction:
            prompt += f"\n{instruction}"
        prompt += "\n請簡潔回應，直接給出你的觀點和行動項目。"
        return prompt
