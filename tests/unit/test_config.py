"""
Unit tests for configuration and environment loading (config.py).
"""

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from sql_auditor.config import load_env


def test_load_env_absent_file_noop(tmp_path: Path):
    """Absent optional .env file should be safely ignored."""
    absent = tmp_path / "does_not_exist.env"
    # Should not raise
    load_env(absent)


def test_load_env_valid_file(tmp_path: Path):
    """Valid .env file loads variables into os.environ."""
    env_file = tmp_path / "test.env"
    env_file.write_text("TEST_CONFIG_KEY=test_value_123\n# comment\n", encoding="utf-8")
    
    load_env(env_file, override=True)
    assert os.environ.get("TEST_CONFIG_KEY") == "test_value_123"
    del os.environ["TEST_CONFIG_KEY"]


def test_load_env_unicode_decode_error_raises(tmp_path: Path):
    """Invalid byte encoding in .env should raise RuntimeError identifying the file."""
    env_file = tmp_path / "corrupt.env"
    # Write invalid UTF-8 bytes
    env_file.write_bytes(b"\x80\x81\xff\xfe")

    with pytest.raises(RuntimeError) as exc_info:
        load_env(env_file)
    assert str(env_file) in str(exc_info.value)
    assert "Failed to read environment file" in str(exc_info.value)


def test_load_env_os_error_raises(tmp_path: Path):
    """I/O or permission errors should raise RuntimeError identifying the file."""
    env_file = tmp_path / "unreadable.env"
    env_file.write_text("FOO=bar", encoding="utf-8")

    with patch("builtins.open", side_effect=OSError("Permission denied")):
        with pytest.raises(RuntimeError) as exc_info:
            load_env(env_file)
        assert str(env_file) in str(exc_info.value)
        assert "Failed to read environment file" in str(exc_info.value)

