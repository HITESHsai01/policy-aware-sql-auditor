"""
Reusable UI Components for Policy-Aware SQL Auditor Console.
"""

from datetime import datetime, timezone
import html
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import streamlit as st

from sql_auditor.answer_builder import StructuredAnswer
from sql_auditor.config import DEFAULT_DB_PATH
from sql_auditor.knowledge_loader import KnowledgeBundle
from sql_auditor.pipeline import PipelineResult
from sql_auditor.router import IntentType
from sql_auditor.schema_inspector import DatabaseSchema
from sql_auditor.ui.presets import PRESET_QUERIES


def extract_revision_history(
    audit_trail: List[Dict[str, Any]],
    final_sql: Optional[str],
) -> Optional[Dict[str, Any]]:
    """Extracts candidate SQL and violation details across revision attempts."""
    rule_attempts = [item for item in audit_trail if item.get("stage") == "rule_audit"]
    if len(rule_attempts) >= 2:
        attempt_1 = rule_attempts[0]
        attempt_2 = rule_attempts[-1]
        return {
            "attempt_1_sql": attempt_1.get("sql", ""),
            "attempt_1_status": attempt_1.get("status", "FAIL"),
            "attempt_1_violations": attempt_1.get("violations", []),
            "attempt_2_sql": attempt_2.get("sql", final_sql or ""),
            "attempt_2_status": attempt_2.get("status", "PASS"),
            "attempt_2_passed": attempt_2.get("passed_rules", []),
            "attempt_2_violations": attempt_2.get("violations", []),
        }
    return None


def render_top_system_bar(schema: DatabaseSchema, bundle: KnowledgeBundle) -> None:
    """Renders high-density system status bar at the top of the console."""
    st.markdown(
        f"""
        <div class="sys-header">
            <div class="sys-title">
                <span>SQL POLICY AUDITOR</span>
                <span class="sys-tag tag-airgap">READ-ONLY AIRGAP</span>
                <span class="sys-tag tag-muted">CORE v0.1.0</span>
            </div>
            <div class="sys-telemetry">
                <div>DATABASE: <span>{DEFAULT_DB_PATH.name}</span> ({len(schema.tables)} tables)</div>
                <div>POLICIES: <span>{len(bundle.concepts)} OKF rules</span></div>
                <div>PARSER: <span>SQLGlot AST (SQLite)</span></div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar(
    schema: DatabaseSchema,
    bundle: KnowledgeBundle,
) -> Tuple[str, str, str, int]:
    """Renders the developer sidebar with execution engine configuration and benchmark presets."""
    with st.sidebar:
        st.markdown("#### ENGINE CONFIGURATION")

        curr_b = st.session_state.get("backend_type", "mock")
        if curr_b == "ollama":
            default_idx = 1
        elif curr_b == "gemini":
            default_idx = 2
        else:
            default_idx = 0

        backend_choice = st.radio(
            "Generator Engine Node",
            options=[
                "Deterministic Simulator (Offline)",
                "Ollama Local LLM (HTTP 11434)",
                "Google Gemini API (Cloud)",
            ],
            index=default_idx,
            help="Choose between offline deterministic simulator, local Ollama daemon, or Google Gemini cloud API.",
        )
        if "Gemini" in backend_choice:
            backend_type = "gemini"
        elif "Ollama" in backend_choice:
            backend_type = "ollama"
        else:
            backend_type = "mock"
        st.session_state["backend_type"] = backend_type

        ollama_model = "llama3.2"
        gemini_model = st.session_state.get("gemini_model", "gemini-2.5-flash")

        if backend_type == "ollama":
            ollama_model = st.text_input(
                "Local Model Tag",
                value=st.session_state.get("ollama_model", "llama3.2"),
                help="Pre-pulled model tag in your local Ollama daemon (e.g. llama3.2, qwen2.5-coder).",
            )
            st.session_state["ollama_model"] = ollama_model
            st.caption("Daemon: `http://localhost:11434` (90s timeout, JSON mode)")
        elif backend_type == "gemini":
            gemini_model = st.selectbox(
                "Gemini Model",
                options=[
                    "gemini-2.5-flash",
                    "gemini-3.5-flash-lite",
                    "gemini-3.5-flash",
                    "gemini-3-flash-preview",
                ],
                index=0,
                help="Google Gemini model version.",
            )
            st.session_state["gemini_model"] = gemini_model
            has_key = bool(os.environ.get("GEMINI_API_KEY"))
            if has_key:
                st.caption(f"Status: Active via `.env` (`{gemini_model}`)")
            else:
                st.caption("Status: `GEMINI_API_KEY` missing in `.env`")

        max_revisions = st.slider(
            "Self-Correction Budget (Revisions)",
            min_value=0,
            max_value=3,
            value=int(st.session_state.get("max_revisions_input", 2)),
            help="Maximum allowable automated feedback cycles before fail-closed abort.",
        )
        st.session_state["max_revisions_input"] = max_revisions

        st.markdown("---")
        st.markdown("#### TEMPORAL HORIZON")
        fiscal_year = st.number_input(
            "Default Fiscal Year (fiscal_year)",
            min_value=2020,
            max_value=2030,
            value=int(st.session_state.get("fiscal_year_input", 2026)),
            step=1,
            help="Enforces policy.fiscal_year@v1 date bounds. Overridden if year is stated explicitly in query.",
        )
        st.session_state["fiscal_year_input"] = fiscal_year
        st.caption("Rule: Explicit year in question takes precedence over this default.")

        st.markdown("---")
        st.markdown("#### BENCHMARK SCENARIOS")
        st.caption("Execute standard test bench scenarios:")

        for preset in PRESET_QUERIES:
            btn_label = f"{preset['icon']} {preset['label']}"
            if st.button(
                btn_label,
                key=f"preset_btn_{preset['id']}",
                use_container_width=True,
                help=preset["description"],
            ):
                st.session_state["query_input"] = preset["question"]
                st.session_state["fiscal_year_input"] = preset["fiscal_year"]
                st.session_state["auto_execute"] = True
                st.rerun()

        st.markdown("---")
        if st.button("RESET TO CLEAN STATE", use_container_width=True):
            st.session_state["last_eval"] = None
            st.session_state["query_input"] = PRESET_QUERIES[0]["question"]
            st.session_state["fiscal_year_input"] = 2026
            st.session_state["auto_execute"] = False
            st.rerun()

    return backend_type, ollama_model, gemini_model, max_revisions


def render_pipeline_stepper(result: PipelineResult) -> None:
    """Renders the 4-step pipeline execution stepper with live statuses."""
    intent_val = result.intent.value.upper()
    intent_class = "val-pass" if result.intent not in (IntentType.AMBIGUOUS, IntentType.UNSUPPORTED) else "val-fail"

    ast_val = "PASS" if (result.guardrail_result and result.guardrail_result.is_valid) else (
        "FAIL" if (result.guardrail_result and not result.guardrail_result.is_valid) else "SKIPPED"
    )
    ast_class = "val-pass" if ast_val == "PASS" else ("val-fail" if ast_val == "FAIL" else "val-skip")

    rule_val = "PASS"
    rule_class = "val-pass"
    if result.rule_audit_result:
        if not result.rule_audit_result.is_compliant:
            rule_val = "VIOLATION"
            rule_class = "val-fail"
        elif result.revisions_attempted > 0:
            rule_val = f"REPAIRED (P{result.revisions_attempted + 1})"
            rule_class = "val-repair"
    elif not result.executed:
        rule_val = "SKIPPED"
        rule_class = "val-skip"

    exec_val = f"200 OK ({result.execution_result.execution_time_ms:.1f}ms)" if (result.executed and result.execution_result) else "FAIL-CLOSED"
    exec_class = "val-pass" if result.executed else "val-fail"

    st.markdown(
        f"""
        <div class="pipeline-stepper">
            <div class="step-node">
                <span class="step-label">1. INTENT ROUTER</span>
                <span class="step-val {intent_class}">{intent_val}</span>
            </div>
            <div class="step-node">
                <span class="step-label">2. AST GUARDRAILS</span>
                <span class="step-val {ast_class}">{ast_val}</span>
            </div>
            <div class="step-node">
                <span class="step-label">3. OKF POLICY AUDIT</span>
                <span class="step-val {rule_class}">{rule_val}</span>
            </div>
            <div class="step-node">
                <span class="step-label">4. DB EXECUTION</span>
                <span class="step-val {exec_class}">{exec_val}</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_decision_verdict(result: PipelineResult, answer: StructuredAnswer) -> None:
    """Renders the top governance decision banner with XSS escaping."""
    if result.executed:
        if result.revisions_attempted > 0:
            st.markdown(
                f"""
                <div class="status-verdict status-repaired">
                    <strong>[APPROVED VIA AUTO-REPAIR]</strong> Candidate SQL initially violated compliance policies, 
                    but was automatically repaired on revision cycle {result.revisions_attempted} and safely executed.
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                """
                <div class="status-verdict status-approved">
                    <strong>[APPROVED - FULL COMPLIANCE]</strong> Candidate query satisfied all deterministic AST guardrails and OKF business policies.
                </div>
                """,
                unsafe_allow_html=True,
            )
    elif result.intent == IntentType.AMBIGUOUS:
        st.markdown(
            f"""
            <div class="status-verdict status-ambiguous">
                <strong>[AMBIGUOUS INQUIRY]</strong> {html.escape(answer.answer_summary)}
            </div>
            """,
            unsafe_allow_html=True,
        )
    elif result.intent == IntentType.UNSUPPORTED:
        st.markdown(
            f"""
            <div class="status-verdict status-ambiguous">
                <strong>[OUT OF SCOPE]</strong> {html.escape(answer.answer_summary)}
            </div>
            """,
            unsafe_allow_html=True,
        )
    elif result.guardrail_result and not result.guardrail_result.is_valid:
        st.markdown(
            f"""
            <div class="status-verdict status-rejected">
                <strong>[SECURITY AST GUARDRAIL BLOCK - FAIL-CLOSED]</strong> {html.escape(result.guardrail_result.error_message or '')}
            </div>
            """,
            unsafe_allow_html=True,
        )
    elif result.rule_audit_result and not result.rule_audit_result.is_compliant:
        st.markdown(
            f"""
            <div class="status-verdict status-rejected">
                <strong>[BUSINESS POLICY VIOLATION - FAIL-CLOSED]</strong> Query violates mandatory governance policies. 
                Execution refused after {result.revisions_attempted} self-correction attempt(s).
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f"""
            <div class="status-verdict status-rejected">
                <strong>[EXECUTION REFUSED]</strong> {html.escape(result.error_message or 'Evaluation aborted.')}
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_metric_strip(result: PipelineResult, max_revisions: int) -> None:
    """Renders the 4-box KPI metric strip."""
    st.markdown(
        f"""
        <div class="metric-strip">
            <div class="metric-box">
                <div class="label">Decision Outcome</div>
                <div class="val" style="color: {'#34d399' if result.executed else '#f43f5e'};">
                    {'APPROVED' if result.executed else 'REJECTED'}
                </div>
            </div>
            <div class="metric-box">
                <div class="label">Intent Classification</div>
                <div class="val">{result.intent.value}</div>
            </div>
            <div class="metric-box">
                <div class="label">Revision Passes</div>
                <div class="val" style="color: {'#fbbf24' if result.revisions_attempted > 0 else '#cbd5e1'};">
                    {result.revisions_attempted} / {max_revisions}
                </div>
            </div>
            <div class="metric-box">
                <div class="label">Engine Latency</div>
                <div class="val">
                    {f"{result.execution_result.execution_time_ms:.2f} ms" if (result.execution_result and result.executed) else "N/A"}
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

