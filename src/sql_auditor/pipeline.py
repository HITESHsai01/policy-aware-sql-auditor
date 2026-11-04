"""
Policy-Aware SQL Auditor End-to-End Pipeline.

Orchestrates the complete flow:
1. Intent Classification & Ambiguity Detection (Router)
2. Lexical Concept & Rule Retrieval (BM25 Retriever)
3. Prompt Construction & Candidate SQL Generation (SQL Generator)
4. Deterministic AST Guardrail Verification (SQL Guardrails)
5. Semantic Business Rule Audit (Rule Auditor)
6. Single Controlled Revision Loop (on Rule Audit failure)
7. Safe Read-Only Execution (Executor)
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

try:
    from sql_auditor.schema_inspector import DatabaseSchema
    from sql_auditor.knowledge_loader import KnowledgeBundle, ConceptDefinition
    from sql_auditor.retrieval import BM25Retriever
    from sql_auditor.router import IntentRouter, IntentType
    from sql_auditor.sql_generator import SQLGenerator
    from sql_auditor.sql_guardrails import validate_sql, GuardrailResult
    from sql_auditor.rule_auditor import RuleAuditor, RuleAuditResult, AuditStatus
    from sql_auditor.executor import SafeExecutor, ExecutionResult
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from sql_auditor.schema_inspector import DatabaseSchema
    from sql_auditor.knowledge_loader import KnowledgeBundle, ConceptDefinition
    from sql_auditor.retrieval import BM25Retriever
    from sql_auditor.router import IntentRouter, IntentType
    from sql_auditor.sql_generator import SQLGenerator
    from sql_auditor.sql_guardrails import validate_sql, GuardrailResult
    from sql_auditor.rule_auditor import RuleAuditor, RuleAuditResult, AuditStatus
    from sql_auditor.executor import SafeExecutor, ExecutionResult


@dataclass
class PipelineResult:
    question: str
    intent: IntentType
    executed: bool
    final_sql: Optional[str] = None
    execution_result: Optional[ExecutionResult] = None
    guardrail_result: Optional[GuardrailResult] = None
    rule_audit_result: Optional[RuleAuditResult] = None
    retrieved_rule_ids: List[str] = field(default_factory=list)
    revisions_attempted: int = 0
    clarification_prompt: Optional[str] = None
    error_message: Optional[str] = None
    audit_trail: List[Dict[str, Any]] = field(default_factory=list)


class AuditorPipeline:
    """End-to-end execution pipeline with deterministic guardrails and rule revision."""

    def __init__(
        self,
        schema: DatabaseSchema,
        bundle: KnowledgeBundle,
        generator: SQLGenerator,
        executor: SafeExecutor,
        retriever: Optional[BM25Retriever] = None,
        router: Optional[IntentRouter] = None,
        rule_auditor: Optional[RuleAuditor] = None,
    ):
        self.schema = schema
        self.bundle = bundle
        self.generator = generator
        self.executor = executor
        self.retriever = retriever or BM25Retriever(bundle=bundle)
        self.router = router or IntentRouter(bundle=bundle, retriever=self.retriever)
        self.rule_auditor = rule_auditor or RuleAuditor(schema=schema)

    def run(
        self,
        question: str,
        context: Optional[Dict[str, Any]] = None,
        max_revisions: int = 1,
    ) -> PipelineResult:
        """
        Executes the question through the full audited pipeline.

        Args:
            question: Natural language question.
            context: Optional context parameters (e.g. fiscal_year=2024).
            max_revisions: Maximum allowable revision attempts on rule failure (default: 1).

        Returns:
            PipelineResult detailing audit outcomes, executed SQL, and query records.
        """
        context = context or {}
        audit_trail: List[Dict[str, Any]] = []

        # 1. Intent Classification
        classification = self.router.classify(question)
        audit_trail.append({
            "stage": "intent_classification",
            "intent": classification.intent.value,
            "confidence": classification.confidence,
            "detected_entities": classification.detected_entities,
        })

        # Early exit on ambiguous or unsupported questions
        if classification.intent == IntentType.AMBIGUOUS:
            return PipelineResult(
                question=question,
                intent=classification.intent,
                executed=False,
                clarification_prompt=classification.clarification_prompt,
                error_message="Question is ambiguous; clarification needed.",
                audit_trail=audit_trail,
            )

        if classification.intent == IntentType.UNSUPPORTED:
            return PipelineResult(
                question=question,
                intent=classification.intent,
                executed=False,
                clarification_prompt=classification.clarification_prompt,
                error_message="Question is out-of-scope or unsupported.",
                audit_trail=audit_trail,
            )

        # 2. Rule & Concept Retrieval
        retrieved_concepts = self.retriever.retrieve(question, top_k=3, expand_related=True)
        raw_rules: List[ConceptDefinition] = [r.concept for r in retrieved_concepts]

        # Filter retrieved rules to those semantically applicable to the question domain
        q_lower = question.lower()
        rules: List[ConceptDefinition] = []
        for r in raw_rules:
            if r.type == "metric":
                if r.id == "metric.departmental_spend":
                    if any(w in q_lower for w in ("spend", "spent", "spending", "expense", "expenses", "cost", "costs")):
                        rules.append(r)
                elif r.id == "metric.active_customer":
                    if any(w in q_lower for w in ("active", "activity", "recent buyer", "recent buyers")):
                        rules.append(r)
                else:
                    rules.append(r)
            elif r.type == "policy":
                if r.id in ("policy.fiscal_year", "policy.expense_reimbursement"):
                    if any(w in q_lower for w in ("spend", "spent", "spending", "expense", "expenses", "reimbursement", "cost", "costs", "fiscal year")):
                        rules.append(r)
                else:
                    rules.append(r)
            else:
                rules.append(r)

        retrieved_ids = [f"{r.id}@v{r.version}" for r in rules if r.type != "index"]

        # If entities detected year (e.g. "year:2024"), add to context
        for entity in classification.detected_entities:
            if entity.startswith("year:") and "fiscal_year" not in context:
                try:
                    context["fiscal_year"] = int(entity.split(":")[1])
                except ValueError:
                    pass

        audit_trail.append({
            "stage": "retrieval",
            "retrieved_rules": retrieved_ids,
            "context": context,
        })

        # 3. Generation & Guardrail/Rule Audit Loop
        revisions_attempted = 0
        candidate_sql = ""
        last_guardrail_res: Optional[GuardrailResult] = None
        last_rule_res: Optional[RuleAuditResult] = None
        feedback: Optional[str] = None

        while revisions_attempted <= max_revisions:
            # Generate candidate SQL
            gen_res = self.generator.generate_candidate_sql(
                question=question,
                rules=rules,
                revision_feedback=feedback,
                context=context,
                attempt=revisions_attempted + 1,
            )
            candidate_sql = gen_res.sql

            # 4. Deterministic Guardrails Check
            guardrail_res = validate_sql(candidate_sql, schema=self.schema)
            last_guardrail_res = guardrail_res

            if not guardrail_res.is_valid:
                audit_trail.append({
                    "stage": "guardrails",
                    "attempt": revisions_attempted + 1,
                    "status": "FAIL",
                    "error": guardrail_res.error_message,
                    "sql": candidate_sql,
                })
                # Guardrail failure: fail closed immediately without revision
                return PipelineResult(
                    question=question,
                    intent=classification.intent,
                    executed=False,
                    final_sql=candidate_sql,
                    guardrail_result=guardrail_res,
                    retrieved_rule_ids=retrieved_ids,
                    revisions_attempted=revisions_attempted,
                    error_message=f"Guardrail violation: {guardrail_res.error_message}",
                    audit_trail=audit_trail,
                )

            # 5. Semantic Rule Audit
            rule_res = self.rule_auditor.audit(candidate_sql, rules=rules, context=context)
            last_rule_res = rule_res

            audit_trail.append({
                "stage": "rule_audit",
                "attempt": revisions_attempted + 1,
                "status": rule_res.status.value,
                "sql": candidate_sql,
                "violations": [v.message for v in rule_res.violations],
                "passed_rules": rule_res.passed_rules,
            })

            # If rule audit passes, query is approved for execution!
            if rule_res.is_compliant:
                break

            # If rule audit fails and revisions remain, trigger revision
            if revisions_attempted < max_revisions:
                revisions_attempted += 1
                feedback = rule_res.summary_message()
            else:
                # Max revisions reached; reject query and refuse execution
                return PipelineResult(
                    question=question,
                    intent=classification.intent,
                    executed=False,
                    final_sql=candidate_sql,
                    guardrail_result=guardrail_res,
                    rule_audit_result=rule_res,
                    retrieved_rule_ids=retrieved_ids,
                    revisions_attempted=revisions_attempted,
                    error_message=f"Rule compliance failure after {revisions_attempted} revision attempt(s): {rule_res.summary_message()}",
                    audit_trail=audit_trail,
                )

        # 6. Safe Read-Only Execution (only reached if both Guardrail and Rule Audit pass)
        exec_res = self.executor.execute(candidate_sql)
        audit_trail.append({
            "stage": "execution",
            "success": exec_res.success,
            "row_count": exec_res.row_count,
            "execution_time_ms": exec_res.execution_time_ms,
            "truncated": exec_res.truncated,
        })

        return PipelineResult(
            question=question,
            intent=classification.intent,
            executed=exec_res.success,
            final_sql=candidate_sql,
            execution_result=exec_res,
            guardrail_result=last_guardrail_res,
            rule_audit_result=last_rule_res,
            retrieved_rule_ids=retrieved_ids,
            revisions_attempted=revisions_attempted,
            error_message=exec_res.error_message,
            audit_trail=audit_trail,
        )

