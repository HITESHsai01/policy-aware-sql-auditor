"""
Policy-Aware SQL Auditor - Enterprise Governance Console.

A deterministic, high-assurance SQL governance and compliance workbench:
- AST Guardrail Inspection (SQLGlot parser, single-statement enforcement, DDL/DML mutation blocking).
- Semantic Business Rule Auditing against versioned Open Knowledge Format (OKF) concepts.
- Multi-turn automated self-correction revision cycles with AST diff inspection.
- Fail-closed execution barrier over SQLite (mode=ro) with full SOC-2 telemetry logging.
"""

import os
from pathlib import Path
import sys
from typing import Tuple

import streamlit as st

# Ensure src directory is available for direct imports
CURRENT_FILE = Path(__file__).resolve()
SRC_DIR = CURRENT_FILE.parent.parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from sql_auditor.audit_log import AuditLogger
from sql_auditor.config import DEFAULT_DB_PATH, KNOWLEDGE_DIR, load_env
from sql_auditor.executor import SafeExecutor
from sql_auditor.knowledge_loader import KnowledgeBundle, load_knowledge_bundle
from sql_auditor.pipeline import AuditorPipeline
from sql_auditor.schema_inspector import DatabaseSchema, inspect_schema
from sql_auditor.sql_generator import (
    GeminiBackend,
    MockGeneratorBackend,
    OllamaBackend,
    SQLGenerator,
)
from sql_auditor.ui import (
    PRESET_MOCK_RESPONSES,
    PRESET_QUERIES,
    extract_revision_history,
    inject_custom_css,
    render_audit_log_tab,
    render_decision_verdict,
    render_knowledge_tab,
    render_metric_strip,
    render_pipeline_stepper,
    render_query_auditor_tab,
    render_schema_tab,
    render_sidebar,
    render_top_system_bar,
)


@st.cache_resource
def get_pipeline_and_components(
    db_path_str: str = str(DEFAULT_DB_PATH),
    knowledge_dir_str: str = str(KNOWLEDGE_DIR),
    backend_type: str = "mock",
    ollama_model: str = "llama3.2",
    gemini_model: str = "gemini-2.5-flash",
    api_key_fingerprint: str = "",
) -> Tuple[AuditorPipeline, AuditLogger, DatabaseSchema, KnowledgeBundle]:
    """Initializes and caches the core backend components for high-speed execution."""
    load_env()
    db_path = Path(db_path_str)
    knowledge_dir = Path(knowledge_dir_str)

    schema = inspect_schema(db_path=db_path)
    bundle = load_knowledge_bundle(knowledge_dir=knowledge_dir, schema=schema)
    executor = SafeExecutor(db_path=db_path)

    if backend_type == "ollama":
        backend = OllamaBackend(model=ollama_model, timeout_seconds=90.0)
    elif backend_type == "gemini":
        backend = GeminiBackend(model=gemini_model)
    else:
        backend = MockGeneratorBackend(responses=PRESET_MOCK_RESPONSES)

    generator = SQLGenerator(backend=backend, schema=schema)
    pipeline = AuditorPipeline(
        schema=schema,
        bundle=bundle,
        generator=generator,
        executor=executor,
    )
    logger = AuditLogger()
    return pipeline, logger, schema, bundle


def init_session_state() -> None:
    """Initializes default Streamlit session state keys."""
    load_env()
    if "query_input" not in st.session_state:
        st.session_state["query_input"] = PRESET_QUERIES[0]["question"]
    if "fiscal_year_input" not in st.session_state:
        st.session_state["fiscal_year_input"] = 2026
    if "max_revisions_input" not in st.session_state:
        st.session_state["max_revisions_input"] = 2
    if "auto_execute" not in st.session_state:
        st.session_state["auto_execute"] = True
    if "last_eval" not in st.session_state:
        st.session_state["last_eval"] = None
    if "backend_type" not in st.session_state:
        st.session_state["backend_type"] = "mock"
    if "ollama_model" not in st.session_state:
        st.session_state["ollama_model"] = "llama3.2"
    if "gemini_model" not in st.session_state:
        st.session_state["gemini_model"] = "gemini-2.5-flash"


def run_dashboard() -> None:
    """Main dashboard entry point for Streamlit application execution."""
    st.set_page_config(
        page_title="Policy-Aware SQL Auditor",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    init_session_state()
    inject_custom_css()

    backend_choice = st.session_state.get("backend_type", "mock")
    ollama_model = st.session_state.get("ollama_model", "llama3.2")
    gemini_model = st.session_state.get("gemini_model", "gemini-2.5-flash")
    api_fingerprint = str(os.environ.get("GEMINI_API_KEY", ""))[-8:]

    pipeline, logger, schema, bundle = get_pipeline_and_components(
        db_path_str=str(DEFAULT_DB_PATH),
        knowledge_dir_str=str(KNOWLEDGE_DIR),
        backend_type=backend_choice,
        ollama_model=ollama_model,
        gemini_model=gemini_model,
        api_key_fingerprint=api_fingerprint,
    )

    # Top System Status Bar
    render_top_system_bar(schema, bundle)

    backend_type, model_tag, g_model, max_revisions = render_sidebar(schema, bundle)
    if (
        backend_type != backend_choice
        or model_tag != ollama_model
        or g_model != gemini_model
    ):
        st.session_state["backend_type"] = backend_type
        st.session_state["ollama_model"] = model_tag
        st.session_state["gemini_model"] = g_model
        st.rerun()

    tab_query, tab_audit, tab_knowledge, tab_schema = st.tabs([
        "QUERY STUDIO",
        "AUDIT LEDGER",
        "POLICY REPOSITORY (OKF)",
        "SCHEMA DICTIONARY",
    ])

    with tab_query:
        render_query_auditor_tab(pipeline, logger, bundle, max_revisions)

    with tab_audit:
        render_audit_log_tab(logger)

    with tab_knowledge:
        render_knowledge_tab(bundle)

    with tab_schema:
        render_schema_tab(schema, DEFAULT_DB_PATH)


if __name__ == "__main__":
    run_dashboard()
