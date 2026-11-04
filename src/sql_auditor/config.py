"""Configuration settings for Policy-Aware SQL Auditor."""

from pathlib import Path

# Base paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_DB_PATH = DATA_DIR / "auditor.db"
KNOWLEDGE_DIR = PROJECT_ROOT / "knowledge"

# Execution limits
DEFAULT_ROW_LIMIT = 100
DEFAULT_TIMEOUT_SECONDS = 2.0
DEFAULT_SQL_DIALECT = "sqlite"
