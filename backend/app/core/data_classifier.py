"""
資料安全分類規則引擎（Data Security Classification Rules Engine）

三層分類系統：
- S1 (Safe)：一般文字，無敏感資料
- S2 (Sensitive)：個資類，如 email、電話、身分證字號
- S3 (Private)：高機密，如 API key、密碼、JWT token

提供 classify / scan / sanitize / restore 四個核心功能。
"""
import enum
import re
import secrets
from dataclasses import dataclass
from typing import Dict, List, Tuple


class SecurityLevel(enum.IntEnum):
    """資料安全等級，數值越大越敏感。"""
    S1 = 1  # Safe — 一般文字
    S2 = 2  # Sensitive — 個資
    S3 = 3  # Private — 高機密


@dataclass
class Match:
    """掃描命中結果。"""
    start: int
    end: int
    matched: str
    pattern_name: str
    level: SecurityLevel


# --- 規則定義 ---
# 格式：(pattern_name, compiled_regex, SecurityLevel)

_S3_PATTERNS: List[Tuple[str, re.Pattern, SecurityLevel]] = [
    # Anthropic API key
    ("anthropic_api_key", re.compile(r"sk-ant-[A-Za-z0-9\-_]{20,}"), SecurityLevel.S3),
    # OpenAI API key
    ("openai_api_key", re.compile(r"sk-[A-Za-z0-9]{20,}"), SecurityLevel.S3),
    # GitHub personal access token (classic & fine-grained)
    ("github_token", re.compile(r"gh[ps]_[A-Za-z0-9]{20,}"), SecurityLevel.S3),
    # AWS access key
    ("aws_access_key", re.compile(r"AKIA[0-9A-Z]{16}"), SecurityLevel.S3),
    # 通用密碼格式：password=xxx / secret=xxx（含引號）
    ("password_assignment", re.compile(
        r"""(?:password|passwd|secret|token)[\s]*[=:][\s]*['"]?[^\s'"]{8,}""",
        re.IGNORECASE,
    ), SecurityLevel.S3),
    # JWT token（三段式 base64）
    ("jwt_token", re.compile(
        r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"
    ), SecurityLevel.S3),
]

_S2_PATTERNS: List[Tuple[str, re.Pattern, SecurityLevel]] = [
    # Email
    ("email", re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}"), SecurityLevel.S2),
    # 台灣手機號碼
    ("phone_tw", re.compile(r"09\d{2}-?\d{3}-?\d{3}"), SecurityLevel.S2),
    # 國際電話（+開頭）
    ("phone_intl", re.compile(r"\+\d{1,3}[\s-]?\d{6,14}"), SecurityLevel.S2),
    # 台灣身分證字號
    ("tw_id", re.compile(r"[A-Z][12]\d{8}"), SecurityLevel.S2),
    # 信用卡號（4 組 4 位數）
    ("credit_card", re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b"), SecurityLevel.S2),
]

_ALL_PATTERNS = _S3_PATTERNS + _S2_PATTERNS

# 遮蔽用的佔位格式
_PLACEHOLDER_FMT = "<<REDACTED:{tag}>>"


def classify(text: str) -> SecurityLevel:
    """掃描文字並回傳最高安全等級。"""
    level = SecurityLevel.S1
    for _name, pattern, pat_level in _ALL_PATTERNS:
        if pattern.search(text):
            if pat_level > level:
                level = pat_level
            # 已達最高等級，提早結束
            if level == SecurityLevel.S3:
                return level
    return level


def scan(text: str) -> List[Match]:
    """掃描文字，回傳所有命中的敏感資料位置與類型。"""
    matches: List[Match] = []
    for name, pattern, level in _ALL_PATTERNS:
        for m in pattern.finditer(text):
            matches.append(Match(
                start=m.start(),
                end=m.end(),
                matched=m.group(),
                pattern_name=name,
                level=level,
            ))
    # 依位置排序
    matches.sort(key=lambda x: x.start)
    return matches


def sanitize(text: str) -> Tuple[str, Dict[str, str]]:
    """遮蔽文字中的敏感資料。

    Returns
    -------
    tuple[str, dict]
        (遮蔽後的文字, 還原對照表 {佔位符: 原始值})
    """
    matches = scan(text)
    if not matches:
        return text, {}

    mapping: Dict[str, str] = {}
    # 從後往前替換，避免 offset 錯位
    result = text
    seen_spans: List[Tuple[int, int]] = []

    for match in reversed(matches):
        # 跳過重疊區間
        if any(match.start >= s and match.end <= e for s, e in seen_spans):
            continue
        tag = secrets.token_hex(4)
        placeholder = _PLACEHOLDER_FMT.format(tag=tag)
        mapping[placeholder] = match.matched
        result = result[:match.start] + placeholder + result[match.end:]
        seen_spans.append((match.start, match.end))

    return result, mapping


def restore(text: str, mapping: Dict[str, str]) -> str:
    """根據對照表還原遮蔽的敏感資料。"""
    result = text
    for placeholder, original in mapping.items():
        result = result.replace(placeholder, original)
    return result


class SecurityBlock(Exception):
    """S3 等級資料阻擋例外"""
    pass


def guard_for_ai(text: str) -> Tuple[str, Dict[str, str]]:
    """送往 AI API 前的安全閘門。

    - S1: 原文放行
    - S2: sanitize 去敏化後放行
    - S3: 拋出 SecurityBlock 阻擋
    """
    level = classify(text)
    if level == SecurityLevel.S3:
        matches = scan(text)
        s3_types = [m.pattern_name for m in matches if m.level == SecurityLevel.S3]
        raise SecurityBlock(f"S3 data detected: {s3_types}")
    if level == SecurityLevel.S2:
        return sanitize(text)
    return text, {}
