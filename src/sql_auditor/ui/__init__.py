"""
UI Package for Policy-Aware SQL Auditor Console.
"""

from sql_auditor.ui.presets import PRESET_MOCK_RESPONSES, PRESET_QUERIES
from sql_auditor.ui.styles import inject_custom_css
from sql_auditor.ui.components import (
    extract_revision_history,
    render_decision_verdict,
    render_metric_strip,
    render_pipeline_stepper,
    render_sidebar,
    render_top_system_bar,
)
from sql_auditor.ui.tabs import (
    render_audit_log_tab,
    render_knowledge_tab,
    render_query_auditor_tab,
    render_schema_tab,
)

__all__ = [
    "PRESET_QUERIES",
    "PRESET_MOCK_RESPONSES",
    "inject_custom_css",
    "extract_revision_history",
    "render_top_system_bar",
    "render_sidebar",
    "render_pipeline_stepper",
    "render_decision_verdict",
    "render_metric_strip",
    "render_query_auditor_tab",
    "render_audit_log_tab",
    "render_knowledge_tab",
    "render_schema_tab",
]

