"""
Aegis 版本資訊 SSOT（Single Source of Truth）

版本號統一從 backend/VERSION 讀取。此檔由 hot_update.py 在成功部署後
以 `git describe --tags --abbrev=0` 的結果寫入，是運行中服務的權威版本號。
"""
from pathlib import Path

VERSION_FILE = Path(__file__).resolve().parents[1] / "VERSION"


def read_version() -> str:
    """讀取 backend/VERSION。檔案不存在時回傳 "0.0.0"。"""
    try:
        return VERSION_FILE.read_text(encoding="utf-8").strip() or "0.0.0"
    except FileNotFoundError:
        return "0.0.0"


__version__ = read_version()
