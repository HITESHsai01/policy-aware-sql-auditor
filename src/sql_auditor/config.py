"""
Configuration Settings for Policy-Aware SQL Auditor.

Defines global file system paths, execution limits, timeouts, and SQL dialect defaults
used throughout the schema inspection, knowledge retrieval, pipeline execution, and audit logging.
"""

import os
from pathlib import Path
from typing import Optional

# Base filesystem directories and database paths
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent.parent
"""Absolute path to the repository root directory."""


def load_env(env_path: Optional[Path] = None, override: bool = False) -> None:
    """Loads key-value pairs from a .env file into os.environ."""
    target_path = env_path or (PROJECT_ROOT / ".env")
    if not target_path.is_file():
        return
    try:
        with open(target_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip("'\"")
                if key and (override or key not in os.environ or not os.environ[key]):
                    os.environ[key] = val
    except Exception:
        pass


# Automatically load .env on config module import
load_env()


DATA_DIR: Path = PROJECT_ROOT / "data"
"""Directory containing the enterprise SQLite database and data fixtures."""

DEFAULT_DB_PATH: Path = DATA_DIR / "auditor.db"
"""Default path to the active enterprise SQLite database file."""

DEFAULT_AUDIT_DB_PATH: Path = DATA_DIR / "audit.db"
"""Dedicated path for the audit trail SQLite database (separated from business data)."""

KNOWLEDGE_DIR: Path = PROJECT_ROOT / "knowledge"
"""Root directory containing versioned Open Knowledge Format (OKF) concept definitions."""

# Safe execution limits and operational defaults
DEFAULT_ROW_LIMIT: int = 100
"""Maximum number of rows returned by query execution before output truncation."""

DEFAULT_TIMEOUT_SECONDS: float = 2.0
"""Wall-clock timeout in seconds for SQLite query execution before interrupting."""

DEFAULT_SQL_DIALECT: str = "sqlite"
"""Target SQL dialect for SQLGlot AST parsing, translation, and validation."""
