"""
Tab View Modules for Policy-Aware SQL Auditor Console.

Contains clean, modular renderers for:
1. Query Studio (Interactive prompt execution, AST verification, and results)
2. Audit Ledger (Forensics, filters, and JSON/CSV export)
3. Policy Repository (OKF concepts, rules, filters)
4. Schema Dictionary (Tables, columns, foreign keys, live preview)
"""

import csv
from datetime import datetime, timezone
import html
import io
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import streamlit as st

from sql_auditor.answer_builder import AnswerBuilder, StructuredAnswer
from sql_auditor.audit_log import AuditLogger, AuditRecord
from sql_auditor.config import DEFAULT_DB_PATH
from sql_auditor.executor import SafeExecutor
from sql_auditor.knowledge_loader import KnowledgeBundle
from sql_auditor.pipeline import AuditorPipeline, PipelineResult
from sql_auditor.schema_inspector import DatabaseSchema, TableInfo
from sql_auditor.ui.components import (
    extract_revision_history,
    render_decision_verdict,
    render_metric_strip,
    render_pipeline_stepper,
)


def render_query_auditor_tab(
    pipeline: AuditorPipeline,
    logger: AuditLogger,
    bundle: KnowledgeBundle,
    max_revisions: int,
) -> None:
    """Renders Tab 1: Interactive Query Studio and Audit Inspector."""
    with st.form("query_form", clear_on_submit=False):
        user_question = st.text_area(
            "QUERY PROMPT // NATURAL LANGUAGE SPECIFICATION",
            value=st.session_state.get("query_input", ""),
            height=78,
            placeholder="e.g. What was the departmental spend for Engineering in 2024?",
        )

        c_submit, c_info = st.columns([1, 3])
        with c_submit:
            submit_button = st.form_submit_button("EXECUTE AUDIT & RUN", use_container_width=True)
        with c_info:
            active_fy = st.session_state.get("fiscal_year_input", 2026)
            st.caption(
                f"Scope: `fiscal_year={active_fy}` | Max Revisions: `{max_revisions}` | Enforcement: `FAIL-CLOSED`"
            )

    should_run = submit_button or st.session_state.get("auto_execute", False)
    if should_run:
        st.session_state["auto_execute"] = False
        st.session_state["query_input"] = user_question

        if not user_question.strip():
            st.warning("Empty query rejected. Please input a question.")
            return

        with st.spinner("Compiling AST and evaluating compliance invariants..."):
            context = {"fiscal_year": int(st.session_state.get("fiscal_year_input", 2026))}
            try:
                pipeline_result = pipeline.run(
                    question=user_question.strip(),
                    context=context,
                    max_revisions=max_revisions,
                )
            except Exception as exc:
                st.error(f"[MODEL GENERATION FAILED] {exc}")
                return
            structured_answer = AnswerBuilder.build_answer(pipeline_result)
            audit_record = logger.log_result(pipeline_result)

            st.session_state["last_eval"] = {
                "result": pipeline_result,
                "answer": structured_answer,
                "record": audit_record,
            }

    last_eval = st.session_state.get("last_eval")
    if not last_eval:
        st.info("Input a natural language query above or select a benchmark scenario from the sidebar.")
        return

    result: PipelineResult = last_eval["result"]
    answer: StructuredAnswer = last_eval["answer"]
    record: AuditRecord = last_eval["record"]

    # 1. Pipeline Verification Stepper
    render_pipeline_stepper(result)

    # 2. Governance Decision Verdict
    render_decision_verdict(result, answer)

    # 3. High-Density KPI Metric Strip
    render_metric_strip(result, max_revisions)

    # 4. Split-Pane Inspection Workstation
    col_sql, col_audit = st.columns([1, 1], gap="medium")

    with col_sql:
        st.markdown("##### SQL COMPILATION & REVISION ARTIFACT")
        revision_info = extract_revision_history(result.audit_trail, result.final_sql)

        if revision_info and result.revisions_attempted > 0:
            is_approved = revision_info.get("attempt_2_status") == "PASS" and result.executed
            tab_diff, tab_attempt1, tab_attempt2 = st.tabs([
                "Unified Diff",
                "Pass 1 (Non-Compliant)",
                "Pass 2 (Repaired)",
            ])

            with tab_diff:
                st.caption("Candidate 1 (Rejected):")
                st.code(revision_info["attempt_1_sql"], language="sql")
                st.caption("Candidate 2 (Repaired):")
                st.code(revision_info["attempt_2_sql"], language="sql")
                if is_approved:
                    st.success("[REPAIR VERIFIED] Injected required predicates and temporal bounds.")
                else:
                    st.error("[REPAIR INCOMPLETE] Violations persist across revisions.")

            with tab_attempt1:
                st.code(revision_info["attempt_1_sql"], language="sql")
                st.error("Audit Verdict: FAIL")
                for viol in revision_info["attempt_1_violations"]:
                    st.markdown(f"- `VIOLATION`: {viol}")

            with tab_attempt2:
                st.code(revision_info["attempt_2_sql"], language="sql")
                if is_approved:
                    st.success("Audit Verdict: PASS")
                    for p in revision_info.get("attempt_2_passed", []):
                        st.markdown(f"- `SATISFIED`: {p}")
                else:
                    st.error("Audit Verdict: FAIL")

        else:
            if result.final_sql:
                st.code(result.final_sql, language="sql")
            else:
                st.caption("No candidate SQL compiled. Query intercepted at router.")

        # Structured Analyst Summary
        st.markdown(
            f"""
            <div class="panel-card">
                <div class="panel-title">Analyst Policy Summary</div>
                <div style="font-size: 13.5px; color: #cbd5e1; line-height: 1.5;">{html.escape(answer.answer_summary)}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if answer.explanation:
            with st.expander("Detailed Policy Justifications", expanded=False):
                st.markdown(answer.explanation)
                if answer.policy_justifications:
                    st.markdown("##### Governing Policy Citations:")
                    for j in answer.policy_justifications:
                        st.markdown(
                            f"- **{j.get('title')}** (`{j.get('rule_id')}@v{j.get('version', '1')}`): {j.get('rationale')}"
                        )

    with col_audit:
        st.markdown("##### COMPLIANCE & AST VERIFICATION MATRIX")

        st.markdown("**1. AST Guardrail Verification**")
        if result.guardrail_result:
            if result.guardrail_result.is_valid:
                st.markdown(
                    """
                    ```text
                    [PASS] Statement Type    : SELECT-only (0 mutators detected)
                    [PASS] Statement Count   : Single statement verified
                    [PASS] Schema Grounding  : Tables & columns verified in catalog
                    [PASS] Dangerous Funcs   : Zero hazardous system functions
                    ```
                    """
                )
            else:
                st.error(f"[AST BLOCKED] {result.guardrail_result.error_message}")
        else:
            st.caption("AST check skipped (query terminated before SQL generation).")

        st.markdown("**2. Retrieved Governing Policies**")
        if result.retrieved_rule_ids:
            for rule_tag in result.retrieved_rule_ids:
                base_id = rule_tag.split("@")[0] if "@" in rule_tag else rule_tag
                concept = bundle.concepts.get(base_id)
                title = concept.title if concept else base_id.replace("_", " ").title()
                st.markdown(f"- `{rule_tag}` — {title}")
        else:
            st.caption("No domain-specific policies matched this query.")

        st.markdown("**3. Policy Invariant Audit Verdict**")
        if result.rule_audit_result and result.rule_audit_result.passed_rules:
            for passed in result.rule_audit_result.passed_rules:
                st.markdown(f"- `[COMPLIANT]` Satisfied `{passed}`")

        if result.rule_audit_result and result.rule_audit_result.violations:
            for v in result.rule_audit_result.violations:
                st.error(f"[{v.violation_type}] Rule: `{v.rule_id}` — {v.message}")
        elif not result.executed and not (result.guardrail_result and not result.guardrail_result.is_valid):
            if result.clarification_prompt:
                st.warning(f"[CLARIFICATION NEEDED] {result.clarification_prompt}")

    st.markdown("---")
    st.markdown("##### RELATIONAL EXECUTION RESULTS")
    if result.executed and result.execution_result and result.execution_result.rows:
        st.caption(
            f"Returned {result.execution_result.row_count} row(s) in {result.execution_result.execution_time_ms:.2f} ms (SQLite mode=ro):"
        )
        st.dataframe(result.execution_result.rows, use_container_width=True)
    elif result.executed and result.execution_result and not result.execution_result.rows:
        st.info("Query executed successfully under read-only mode, returning 0 records.")
    else:
        st.markdown(
            """
            <div style="background: rgba(244, 63, 94, 0.05); border: 1px dashed rgba(244, 63, 94, 0.3); border-radius: 4px; padding: 12px; color: #cbd5e1; font-size: 13px;">
                <strong>FAIL-CLOSED SECURITY ENFORCEMENT:</strong> Database access was denied by the auditor. Zero queries were executed against storage.
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_audit_log_tab(logger: AuditLogger) -> None:
    """Renders Tab 2: Persistent Audit Log History & Forensics."""
    records = logger.get_recent_records(limit=100)
    if not records:
        st.info("Zero audit records found. Run queries in the Query Studio to record traces.")
        return

    total_audited = len(records)
    executed_count = sum(1 for r in records if r.executed)
    guardrail_fails = sum(1 for r in records if r.guardrail_status == "FAIL")
    rule_fails = sum(1 for r in records if r.rule_audit_status == "FAIL" and not r.executed)
    avg_latency = (
        sum(r.execution_time_ms for r in records if r.executed) / max(executed_count, 1)
    )

    st.markdown(
        f"""
        <div class="metric-strip">
            <div class="metric-box">
                <div class="label">Total Evaluated</div>
                <div class="val">{total_audited}</div>
            </div>
            <div class="metric-box">
                <div class="label">Compliance Approval Rate</div>
                <div class="val" style="color: #34d399;">{(executed_count / total_audited) * 100:.1f}%</div>
            </div>
            <div class="metric-box">
                <div class="label">Fail-Closed Block Rate</div>
                <div class="val" style="color: #f43f5e;">{((guardrail_fails + rule_fails) / total_audited) * 100:.1f}%</div>
            </div>
            <div class="metric-box">
                <div class="label">Mean Execution Time</div>
                <div class="val">{avg_latency:.2f} ms</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    f_col1, f_col2 = st.columns([1, 2])
    with f_col1:
        status_filter = st.selectbox(
            "Filter Outcome",
            options=["All Records", "Executed (Approved)", "Guardrail Violations", "Rule Violations"],
            index=0,
        )
    with f_col2:
        search_query = st.text_input("Search Logs", placeholder="Search by question, request ID, or intent...")

    filtered = records
    if status_filter == "Executed (Approved)":
        filtered = [r for r in filtered if r.executed]
    elif status_filter == "Guardrail Violations":
        filtered = [r for r in filtered if r.guardrail_status == "FAIL"]
    elif status_filter == "Rule Violations":
        filtered = [r for r in filtered if r.rule_audit_status == "FAIL" and not r.executed]

    if search_query.strip():
        sq = search_query.strip().lower()
        filtered = [
            r for r in filtered
            if sq in r.question.lower()
            or sq in r.request_id.lower()
            or sq in r.intent.lower()
            or (r.final_sql and sq in r.final_sql.lower())
        ]

    st.caption(f"Showing {len(filtered)} of {total_audited} persistent audit entries.")

    table_rows = []
    for r in filtered:
        table_rows.append({
            "Timestamp (UTC)": r.timestamp,
            "Request ID": r.request_id[:8] + "...",
            "Intent": r.intent,
            "Executed": "[PASS]" if r.executed else "[FAIL]",
            "Guardrail": r.guardrail_status,
            "Rule Audit": r.rule_audit_status,
            "Revisions": r.revisions_attempted,
            "Latency (ms)": f"{r.execution_time_ms:.2f}",
            "Rows": r.row_count,
            "Question": r.question,
        })
    st.dataframe(table_rows, use_container_width=True)

    st.markdown("##### Trace Inspector")
    record_map = {f"{r.timestamp} — {r.question[:45]} ({r.request_id[:8]})": r for r in filtered}
    if record_map:
        selected_key = st.selectbox("Select Record to Inspect Full JSON Trace", options=list(record_map.keys()))
        selected_record = record_map[selected_key]
        with st.expander(f"Audit Record Trace: {selected_record.request_id}", expanded=True):
            st.json(selected_record.to_dict())

    st.markdown("---")
    st.markdown("##### Export Compliance Telemetry")
    exp_c1, exp_c2 = st.columns(2)
    with exp_c1:
        export_json_str = json.dumps([r.to_dict() for r in filtered], indent=2)
        st.download_button(
            "Download Trace Log (JSON)",
            data=export_json_str,
            file_name=f"audit_logs_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json",
            mime="application/json",
            use_container_width=True,
        )
    with exp_c2:
        csv_buffer = io.StringIO()
        if filtered:
            fieldnames = list(filtered[0].to_dict().keys())
            writer = csv.DictWriter(csv_buffer, fieldnames=fieldnames)
            writer.writeheader()
            for r in filtered:
                d = r.to_dict()
                d["retrieved_rules"] = json.dumps(d["retrieved_rules"])
                d["rule_violations"] = json.dumps(d["rule_violations"])
                writer.writerow(d)
        st.download_button(
            "Download Ledger (CSV)",
            data=csv_buffer.getvalue(),
            file_name=f"audit_logs_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
            use_container_width=True,
        )


def render_knowledge_tab(bundle: KnowledgeBundle) -> None:
    """Renders Tab 3: Open Knowledge Format (OKF) Policy Repository."""
    concepts = list(bundle.concepts.values())
    type_options = ["All Types"] + sorted(list({c.type for c in concepts}))
    selected_type = st.selectbox("Filter Concepts by Type", options=type_options, index=0)

    filtered = concepts
    if selected_type != "All Types":
        filtered = [c for c in filtered if c.type == selected_type]

    st.caption(f"Displaying {len(filtered)} verified OKF concept specifications.")

    for concept in filtered:
        with st.expander(f"[{concept.type.upper()}] {concept.title} ({concept.id}@v{concept.version})", expanded=False):
            c1, c2 = st.columns([3, 1])
            with c1:
                st.markdown(f"**Description**: {concept.description}")
                st.markdown(f"**Governed Tables**: {', '.join(f'`{t}`' for t in concept.tables)}")
                st.markdown(f"**Tags**: {', '.join(f'`{t}`' for t in concept.tags)}")
            with c2:
                st.markdown(f"**Type**: `{concept.type.upper()}`")
                st.markdown(f"**Version**: `v{concept.version}`")

            if concept.required_filters:
                st.markdown("##### Mandatory Predicate Filters:")
                rows = []
                for rf in concept.required_filters:
                    rows.append({
                        "Column": rf.column,
                        "Operator": rf.operator or "=",
                        "Enforced Value / Type": str(rf.value if rf.value is not None else rf.type),
                        "Window": f"{rf.window_days} days" if rf.window_days else "N/A",
                    })
                st.table(rows)

            if concept.forbidden_substitutes:
                st.markdown("##### Prohibited Proxy Columns:")
                for sub in concept.forbidden_substitutes:
                    st.error(f"Prohibited: `{sub.column}` — {sub.reason}")

            if concept.required_joins:
                st.markdown("##### Mandatory Relational Joins:")
                for rj in concept.required_joins:
                    st.markdown(f"- Join `{rj.from_table}` with `{rj.to_table}` ON `{rj.on}`")


def render_schema_tab(schema: DatabaseSchema, db_path: Path = DEFAULT_DB_PATH) -> None:
    """Renders Tab 4: Database Schema Dictionary & Live Data Preview."""
    table_names = sorted(schema.tables.keys())
    selected_table = st.selectbox("Select Table to Inspect", options=table_names)
    table_info: TableInfo = schema.tables[selected_table]

    st.markdown(
        f"""
        <div class="metric-strip" style="grid-template-columns: repeat(2, 1fr);">
            <div class="metric-box">
                <div class="label">Column Count</div>
                <div class="val">{len(table_info.columns)}</div>
            </div>
            <div class="metric-box">
                <div class="label">Foreign Key Constraints</div>
                <div class="val">{len(table_info.foreign_keys)}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(f"##### Column Schema: `{table_info.name}`")
    col_rows = []
    for col in table_info.columns.values():
        col_rows.append({
            "Column Name": col.name,
            "Type": col.data_type,
            "Primary Key": "YES" if col.is_pk else "NO",
            "Not Null": "YES" if col.not_null else "NO",
        })
    st.table(col_rows)

    st.markdown(f"##### Sample Records Preview (Top 5 Rows): `{table_info.name}`")
    try:
        executor = SafeExecutor(db_path=db_path)
        if selected_table not in schema.tables:
            st.error(f"Unknown table: {selected_table}")
            return
        sample = executor.execute(f'SELECT * FROM "{selected_table}" LIMIT 5;')
        if sample.success and sample.rows:
            st.dataframe(sample.rows, use_container_width=True)
            st.caption(f"Fetched {sample.row_count} record(s) in {sample.execution_time_ms:.2f} ms.")
        else:
            st.info(f"Table `{selected_table}` is empty.")
    except Exception as exc:
        st.error(f"Failed to preview data: {exc}")

