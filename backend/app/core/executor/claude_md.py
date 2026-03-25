"""向後相容 — 已搬遷至 config_md.py，此檔案僅 re-export。"""
from app.core.executor.config_md import (  # noqa: F401
    build_config_md,
    build_config_md as build_claude_md,  # 向後相容別名
    PROVIDER_CONFIG,
    get_config_filename,
    get_dot_dir,
)
