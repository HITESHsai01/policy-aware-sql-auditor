"""
Policy-Aware SQL Auditor - Interactive Streamlit Dashboard Launcher.

Root entry point for executing the Policy-Aware SQL Auditor web application.

Usage:
    streamlit run app.py
"""

import sys
from pathlib import Path

# Ensure 'src' is present on sys.path for direct module resolution
ROOT_DIR = Path(__file__).resolve().parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from sql_auditor.dashboard import run_dashboard

if __name__ == "__main__":
    run_dashboard()
