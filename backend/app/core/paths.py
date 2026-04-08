"""Centralized path constants for the Aegis backend."""
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
INSTALL_ROOT = BACKEND_ROOT.parent
AEGIS_DIR = INSTALL_ROOT / ".aegis"
UPLOADS_DIR = BACKEND_ROOT / "uploads"
PORTRAITS_DIR = UPLOADS_DIR / "portraits"
SPRITES_DIR = UPLOADS_DIR / "sprites"
WORKSPACES_ROOT = AEGIS_DIR / "workspaces"
ABORT_DIR = AEGIS_DIR / "abort"
PLANS_DIR = AEGIS_DIR / "plans"
EXCHANGE_DIR = AEGIS_DIR / "shared" / "exchange"
DB_FILE = BACKEND_ROOT / "local.db"
ENV_FILE = BACKEND_ROOT / ".env"
VERSION_FILE = BACKEND_ROOT / "VERSION"
