"""
Answer Builder Module.

Synthesizes pipeline results into structured, consumer-ready responses
with natural-language summaries, executed SQL, result datasets, and
explicit business-rule version citations.
"""

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

try:
    from sql_auditor.pipeline import PipelineResult
    from sql_auditor.router import IntentType
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from sql_auditor.pipeline import PipelineResult
    from sql_auditor.router import IntentType


@dataclass
class StructuredAnswer:
    status: str  # success, rejected_rule_violation, rejected_guardrail_violation, ambiguous, unsupported
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

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class AnswerBuilder:
    """Constructs structured responses from PipelineResult."""

    @staticmethod
    def build_answer(result: PipelineResult) -> StructuredAnswer:
        # 1. Ambiguous query
        if result.intent == IntentType.AMBIGUOUS:
            return StructuredAnswer(
                status="ambiguous",
                answer_summary=(
                    result.clarification_prompt
                    or "Your question is too broad or missing parameters. Please clarify."
                ),
                clarification_prompt=result.clarification_prompt,
                diagnostics={"intent": result.intent.value, "audit_trail": result.audit_trail},
            )

        # 2. Unsupported query
        if result.intent == IntentType.UNSUPPORTED:
            return StructuredAnswer(
                status="unsupported",
                answer_summary=(
                    result.clarification_prompt
                    or "This request is out-of-scope for the corporate database."
                ),
                clarification_prompt=result.clarification_prompt,
                diagnostics={"intent": result.intent.value, "audit_trail": result.audit_trail},
            )

        # 3. Guardrail violation
        if result.guardrail_result and not result.guardrail_result.is_valid:
            return StructuredAnswer(
                status="rejected_guardrail_violation",
                answer_summary=f"Query rejected by safety guardrails: {result.guardrail_result.error_message}",
                sql_query=result.final_sql,
                cited_rules=result.retrieved_rule_ids,
                revisions_attempted=result.revisions_attempted,
                diagnostics={
                    "intent": result.intent.value,
                    "guardrail_error": result.guardrail_result.error_message,
                    "audit_trail": result.audit_trail,
                },
            )

        # 4. Rule audit violation
        if result.rule_audit_result and not result.rule_audit_result.is_compliant:
            summary = (
                f"Query rejected due to business compliance failure(s) after {result.revisions_attempted} revision attempt(s):\n"
                + result.rule_audit_result.summary_message()
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
            )

        # 5. Successful Execution
        if result.executed and result.execution_result and result.execution_result.success:
            exec_res = result.execution_result
            summary = AnswerBuilder._format_success_summary(result)
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
        )

    @staticmethod
    def _format_success_summary(result: PipelineResult) -> str:
        exec_res = result.execution_result
        if not exec_res or not exec_res.rows:
            return "Query executed successfully, returning 0 records."

        n_rows = exec_res.row_count
        row_word = "record" if n_rows == 1 else "records"

        # If 1 row and 1 or 2 columns, provide succinct answer
        if n_rows == 1:
            first_row = exec_res.rows[0]
            items = [f"{k}: {v}" for k, v in first_row.items()]
            return f"Query returned 1 {row_word}: {', '.join(items)}."

        return f"Query executed successfully, returning {n_rows} {row_word} verified against {len(result.retrieved_rule_ids)} rule(s)."
