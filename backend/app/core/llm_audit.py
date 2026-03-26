"""
LLM Audit Logger — 記錄每次 LLM 呼叫的元數據（JSONL 格式）

為後續的成本追蹤和 API Proxy 層提供數據基礎。
每筆記錄包含：provider、model、token 用量、耗時、狀態等。
"""
import json
import logging
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# 預設 JSONL 輸出路徑（相對於 backend/）
_DEFAULT_AUDIT_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "llm_audit.jsonl"


@dataclass
class LLMCallRecord:
    """單次 LLM 呼叫的元數據"""
    provider: str = ""
    model: str = ""
    card_id: int = 0
    member_id: Optional[int] = None
    start_time: float = 0.0
    end_time: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    status: str = ""          # "success" | "error" | "aborted"
    error: str = ""
    cost_usd: float = 0.0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    duration_ms: int = 0
    session_id: Optional[str] = None

    def to_dict(self) -> dict:
        """序列化為可寫入 JSONL 的 dict"""
        d = asdict(self)
        # 移除空值欄位以節省空間
        return {k: v for k, v in d.items() if v is not None and v != "" and v != 0 and v != 0.0}


def log_llm_call(record: LLMCallRecord, path: Optional[Path] = None) -> None:
    """將 LLMCallRecord 寫入 JSONL 檔案（append 模式）"""
    out_path = path or _DEFAULT_AUDIT_PATH
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
        logger.debug(f"[LLMAudit] logged call: provider={record.provider} model={record.model} "
                     f"tokens={record.input_tokens}+{record.output_tokens} status={record.status}")
    except Exception as e:
        logger.warning(f"[LLMAudit] write failed: {e}")


class LLMAuditContext:
    """Context manager — 自動計時、捕捉錯誤、寫入審計日誌

    用法：
        ctx = LLMAuditContext(provider="claude", card_id=42, member_id=1)
        with ctx:
            # 執行 LLM 呼叫 ...
            pass
        # with 結束後自動 log
        # 可在 with 區塊內設定 ctx.record 的 token 欄位
    """

    def __init__(self, provider: str = "", card_id: int = 0,
                 member_id: Optional[int] = None,
                 audit_path: Optional[Path] = None):
        self.record = LLMCallRecord(
            provider=provider,
            card_id=card_id,
            member_id=member_id,
        )
        self._audit_path = audit_path

    def __enter__(self) -> "LLMAuditContext":
        self.record.start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.record.end_time = time.time()
        self.record.duration_ms = int((self.record.end_time - self.record.start_time) * 1000)

        if exc_type is not None:
            self.record.status = self.record.status or "error"
            self.record.error = str(exc_val) if exc_val else exc_type.__name__

        # 若未設定 status，預設為 success
        if not self.record.status:
            self.record.status = "success"

        log_llm_call(self.record, self._audit_path)
        # 不吞掉例外
        return None

    def fill_from_token_info(self, token_info: dict) -> None:
        """從 stream_parsers 回傳的 token_info dict 填入 record"""
        if not token_info:
            return
        self.record.model = token_info.get("model", "") or self.record.model
        self.record.input_tokens = token_info.get("input_tokens", 0)
        self.record.output_tokens = token_info.get("output_tokens", 0)
        self.record.cost_usd = token_info.get("cost_usd", 0.0)
        self.record.cache_read_tokens = token_info.get("cache_read_tokens", 0)
        self.record.cache_creation_tokens = token_info.get("cache_creation_tokens", 0)
        self.record.session_id = token_info.get("session_id")
