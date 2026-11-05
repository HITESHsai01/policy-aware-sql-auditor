"""
Answer Builder Module for Policy-Aware SQL Auditor.

Synthesizes pipeline execution and audit results into structured, human-friendly responses.
Constructs natural-language summaries, conversational explanations, executed SQL queries,
tabular datasets, and explicit compliance-policy citations.
"""

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from sql_auditor.pipeline import PipelineResult
from sql_auditor.router import IntentType


@dataclass
class StructuredAnswer:
    status: str
    answer_summary: str
    sql_query: Optional[str] = None
    columns: List[str] = field(default_factory=list)
    rows: List[Dict[str, Any]] = field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    cited_rules: List[str] = field(default_factory=list)
    revisions_attempted: int = 0
    diagnostics: Dict[str, Any] = field(default_factory=dict)
    clarification_prompt: Optional[str] = None
    explanation: Optional[str] = None
    policy_justifications: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Serializes the StructuredAnswer instance to a dictionary."""
        return asdict(self)


class AnswerBuilder:
    """Constructs structured, consumer-ready responses from PipelineResult.

    Translates AST audits, guardrail evaluations, and SQLite query outputs into
    clear, polite, and conversational explanations grounded in corporate compliance policies.
    """

    @classmethod
    def build_answer(cls, result: PipelineResult) -> StructuredAnswer:
        """Constructs a StructuredAnswer from an end-to-end PipelineResult.

        Args:
            result: The PipelineResult containing intent, AST checks, rule audits,
                and SQLite execution outcomes.

        Returns:
            A StructuredAnswer instance with humanized summaries, data, and policy grounding.
        """
        # 1. Ambiguous query: Request clarification courteously
        if result.intent == IntentType.AMBIGUOUS:
            if result.clarification_prompt:
                summary = (
                    "I would be glad to help answer your query, but I need a little more detail "
                    f"to formulate an accurate calculation. {result.clarification_prompt}"
                )
            else:
                summary = (
                    "Your question appears broad or missing key parameters. "
                    "Please specify the target fiscal year or department so that we can retrieve the correct data."
                )
            return StructuredAnswer(
                status="ambiguous",
                answer_summary=summary,
                clarification_prompt=result.clarification_prompt or summary,
                diagnostics={"intent": result.intent.value, "audit_trail": result.audit_trail},
                explanation=(
                    "Ambiguous queries are paused before SQL generation to ensure data integrity and prevent "
                    "misleading aggregations."
                ),
            )

        # 2. Unsupported query: Polite explanation of domain boundaries
        if result.intent == IntentType.UNSUPPORTED:
            if result.clarification_prompt:
                summary = (
                    "I am unable to process this request because it falls outside the system's analytical domain. "
                    f"{result.clarification_prompt}"
                )
            else:
                summary = (
                    "I am unable to process this request because it falls outside the system's operational scope. "
                    "This system only supports corporate financial data and enterprise metric inquiries."
                )
            return StructuredAnswer(
                status="unsupported",
                answer_summary=summary,
                clarification_prompt=result.clarification_prompt or summary,
                diagnostics={"intent": result.intent.value, "audit_trail": result.audit_trail},
                explanation=(
                    "The system scope is restricted to corporate financial databases and metrics to protect against "
                    "out-of-domain requests and prompt injections."
                ),
            )

        # 3. Guardrail violation: Friendly, informative security framing
        if result.guardrail_result and not result.guardrail_result.is_valid:
            error_msg = result.guardrail_result.error_message or "Unknown guardrail safety violation."
            summary = (
                f"Query rejected by safety guardrails: {error_msg} "
                "For database safety and data governance, only read-only SELECT queries against "
                "allowlisted schema tables and columns are permitted."
            )
            return StructuredAnswer(
                status="rejected_guardrail_violation",
                answer_summary=summary,
                sql_query=result.final_sql,
                cited_rules=result.retrieved_rule_ids,
                revisions_attempted=result.revisions_attempted,
                diagnostics={
                    "intent": result.intent.value,
                    "guardrail_error": result.guardrail_result.error_message,
                    "audit_trail": result.audit_trail,
                },
                explanation=(
                    "Deterministic AST safety guardrails ensure that destructive statements (DROP, ALTER, INSERT, UPDATE, DELETE), "
                    "stacked queries, unallowlisted tables, and unauthorized system functions are rejected fail-closed."
                ),
            )

        # 4. Rule audit violation: Clear conversational reasoning with rule citations and quotes
        if result.rule_audit_result and not result.rule_audit_result.is_compliant:
            violations_detail = result.rule_audit_result.summary_message()
            justifications = cls.generate_policy_justifications(result)
            rationales = [j["rationale"] for j in justifications if j.get("status") == "violated"]
            rationale_text = (
                "\n\nBusiness Compliance Governance Rationale:\n"
                + "\n".join(f"- {r}" for r in dict.fromkeys(rationales))
                if rationales else ""
            )

            summary = (
                f"Query rejected due to business compliance failure(s) after {result.revisions_attempted} revision attempt(s):\n"
                f"{violations_detail}{rationale_text}\n\n"
                "Please refine your query or provide the required constraints to align with enterprise reporting standards."
            )

            return StructuredAnswer(
                status="rejected_rule_violation",
                answer_summary=summary,
                sql_query=result.final_sql,
                cited_rules=result.retrieved_rule_ids,
                revisions_attempted=result.revisions_attempted,
                diagnostics={
                    "intent": result.intent.value,
                    "violations": [v.message for v in result.rule_audit_result.violations],
                    "audit_trail": result.audit_trail,
                },
                explanation=(
                    "Semantic rule auditing verifies candidate SQL queries against Open Knowledge Format (OKF) business rules "
                    "to prevent common accounting and metric distortions before any query is executed."
                ),
                policy_justifications=justifications,
            )

        # 5. Successful Execution: Humanized summary and compliance citation
        if result.executed and result.execution_result and result.execution_result.success:
            exec_res = result.execution_result
            summary = cls._format_success_summary(result)
            justifications = cls.generate_policy_justifications(result)

            explanation_parts = [
                f"The query was successfully verified and executed in {exec_res.execution_time_ms:.2f} ms, returning {exec_res.row_count} record(s)."
            ]
            if result.retrieved_rule_ids:
                explanation_parts.append(
                    f"Compliance verified against: {', '.join(result.retrieved_rule_ids)}."
                )

            return StructuredAnswer(
                status="success",
                answer_summary=summary,
                sql_query=result.final_sql,
                columns=exec_res.columns,
                rows=exec_res.rows,
                row_count=exec_res.row_count,
                truncated=exec_res.truncated,
                cited_rules=result.retrieved_rule_ids,
                revisions_attempted=result.revisions_attempted,
                diagnostics={
                    "intent": result.intent.value,
                    "execution_time_ms": exec_res.execution_time_ms,
                    "audit_trail": result.audit_trail,
                },
                explanation=" ".join(explanation_parts),
                policy_justifications=justifications,
            )

        # 6. Fallback execution failure
        err = result.error_message or "Unknown execution error."
        return StructuredAnswer(
            status="error",
            answer_summary=f"Failed to execute query: {err}",
            sql_query=result.final_sql,
            cited_rules=result.retrieved_rule_ids,
            revisions_attempted=result.revisions_attempted,
            diagnostics={"audit_trail": result.audit_trail},
            explanation="The query passed validation checks but encountered a database runtime exception during execution.",
        )

    @classmethod
    def _format_success_summary(cls, result: PipelineResult) -> str:
        """Builds a humanized, conversational summary for successful query executions."""
        exec_res = result.execution_result
        if not exec_res or not exec_res.rows:
            return "Query executed successfully, returning 0 records matching your criteria. All compliance policies were satisfied."

        n_rows = exec_res.row_count
        row_word = "record" if n_rows == 1 else "records"

        # If 1 row, format a clear conversational statement
        if n_rows == 1:
            first_row = exec_res.rows[0]
            items = [f"{k}: {v}" for k, v in first_row.items()]
            items_str = ", ".join(items)
            if result.retrieved_rule_ids:
                rules_str = ", ".join(result.retrieved_rule_ids)
                return (
                    f"Based on verified corporate data, the query returned 1 {row_word}: {items_str}. "
                    f"This calculation complies with governing policy {rules_str}."
                )
            return f"Based on verified corporate data, the query returned 1 {row_word}: {items_str}."

        # Multi-row execution
        if result.retrieved_rule_ids:
            rules_str = ", ".join(result.retrieved_rule_ids)
            return (
                f"Query executed successfully, returning {n_rows} {row_word} verified against "
                f"{len(result.retrieved_rule_ids)} rule(s) ({rules_str})."
            )
        return f"Query executed successfully, returning {n_rows} {row_word}."

    @staticmethod
    def generate_policy_justifications(result: PipelineResult) -> List[Dict[str, Any]]:
        """Generates structured policy justifications explaining the business rationale for each cited rule."""
        justifications: List[Dict[str, Any]] = []

        # Knowledge mapping for core enterprise rules
        known_rationales = {
            "metric.departmental_spend": (
                "Departmental Spend Metric",
                "Calculates approved expenditures by department. Requires filtering by expenses.status = 'approved' "
                "to exclude pending, rejected, or draft expenses from official spend figures.",
            ),
            "metric.active_customer": (
                "Active Customer Metric",
                "Defines active customers based on order activity within the rolling 90-day window and status='active' "
                "to ensure churned accounts do not inflate retention reports.",
            ),
            "policy.fiscal_year": (
                "Fiscal Year Accounting Policy",
                "Enforces calendar-aligned fiscal boundaries (January 1 through December 31) "
                "to prevent period-mismatch errors in financial reporting.",
            ),
            "policy.expense_reimbursement": (
                "Expense Reimbursement Policy",
                "Governs employee expense claims, requiring approved verification status and department foreign key integrity.",
            ),
            "policy.order_status": (
                "Order Status Compliance Policy",
                "Specifies valid order fulfillment lifecycles and canonical status transitions for revenue recognition.",
            ),
        }

        # 1. Justifications for retrieved and satisfied rules
        for rule_id_tag in result.retrieved_rule_ids:
            base_id = rule_id_tag.split("@")[0] if "@" in rule_id_tag else rule_id_tag
            version = rule_id_tag.split("@v")[1] if "@v" in rule_id_tag else "1"
            title, rationale = known_rationales.get(
                base_id,
                (
                    base_id.replace("_", " ").title(),
                    "Enforces enterprise business consistency and schema integrity constraints.",
                ),
            )
            justifications.append({
                "rule_id": base_id,
                "version": version,
                "title": title,
                "rationale": rationale,
                "status": "satisfied" if result.executed else "evaluated",
            })

        # 2. Justifications for violated rules
        if result.rule_audit_result and result.rule_audit_result.violations:
            for v in result.rule_audit_result.violations:
                base_id = v.rule_id
                title, base_rationale = known_rationales.get(
                    base_id,
                    (base_id.replace("_", " ").title(), "Mandatory business rule constraint."),
                )
                justifications.append({
                    "rule_id": base_id,
                    "version": str(v.rule_version),
                    "title": title,
                    "rationale": f"{base_rationale} Violation details: {v.message}",
                    "status": "violated",
                    "violation_type": v.violation_type,
                })

        return justifications
