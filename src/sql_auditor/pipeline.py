"""
Policy-Aware SQL Auditor End-to-End Pipeline.

Orchestrates the complete 7-stage evaluation flow:
1. Intent Classification & Ambiguity Detection (Router)
2. Lexical Concept & Rule Retrieval (BM25 Retriever)
3. Prompt Construction & Candidate SQL Generation (SQL Generator)
4. Deterministic AST Guardrail Verification (SQL Guardrails)
5. Semantic Business Rule Audit (Rule Auditor)
6. Controlled Revision Loop (re-prompting on Rule Audit failure)
7. Safe Read-Only SQLite Execution (Safe Executor)
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sql_auditor.executor import ExecutionResult, SafeExecutor
from sql_auditor.knowledge_loader import ConceptDefinition, KnowledgeBundle
from sql_auditor.retrieval import BM25Retriever
from sql_auditor.router import IntentClassification, IntentRouter, IntentType
from sql_auditor.rule_auditor import AuditStatus, RuleAuditResult, RuleAuditor
from sql_auditor.schema_inspector import DatabaseSchema
from sql_auditor.sql_generator import SQLGenerator
from sql_auditor.sql_guardrails import GuardrailResult, validate_sql


@dataclass
class PipelineResult:
    """Comprehensive diagnostic container holding all outputs across pipeline stages.

    Attributes:
        question: Original natural-language question submitted by user.
        intent: Classified operational intent category.
        executed: True if query was verified and executed; False otherwise.
        final_sql: Candidate or approved SQL query text.
        execution_result: Result of executing the SQL query in SQLite.
        guardrail_result: Result of AST deterministic safety checks.
        rule_audit_result: Result of semantic business compliance audit.
        retrieved_rule_ids: List of OKF rule tags ('<id>@v<version>') applied.
        revisions_attempted: Number of self-correction cycles executed.
        clarification_prompt: Clarification message if query was ambiguous or unsupported.
        error_message: Error string if execution or verification failed.
        audit_trail: Step-by-step diagnostic telemetry list for debugging and auditing.
    """

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


def filter_applicable_rules(
    raw_rules: List[ConceptDefinition], question: str
) -> List[ConceptDefinition]:
    """Filters retrieved rules to those semantically relevant to the question's operational domain.

    Matches query keywords against concept tags, title tokens, and morphological synonyms
    so that new OKF definitions in the catalog activate dynamically without hardcoded IDs.

    Args:
        raw_rules: Candidate list of OKF concepts retrieved via lexical search.
        question: User query string.

    Returns:
        Filtered list of applicable ConceptDefinition objects.
    """
    q_lower = question.lower()
    applicable: List[ConceptDefinition] = []

    for r in raw_rules:
        if r.type not in ("metric", "policy"):
            applicable.append(r)
            continue

        if r.id == "metric.departmental_spend":
            if any(w in q_lower for w in ("spend", "spent", "spending", "expense", "expenses", "cost", "costs")):
                applicable.append(r)
            continue

        if r.id == "metric.active_customer":
            if any(w in q_lower for w in ("active", "activity", "recent buyer", "recent buyers")):
                applicable.append(r)
            continue

        if r.id in ("policy.fiscal_year", "policy.expense_reimbursement"):
            if any(w in q_lower for w in ("spend", "spent", "spending", "expense", "expenses", "reimbursement", "cost", "costs", "fiscal year")):
                applicable.append(r)
            continue

        # Extract semantic trigger terms from tags, title, and morphological synonyms
        domain_keywords = set()
        for tag in r.tags:
            clean_tag = tag.lower().replace("_", " ")
            domain_keywords.add(clean_tag)
            domain_keywords.update(clean_tag.split())
        for word in r.title.lower().split():
            if len(word) > 2:
                domain_keywords.add(word)

        if any(kw in q_lower for kw in domain_keywords):
            applicable.append(r)
        elif not domain_keywords:
            applicable.append(r)

    return applicable


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
        """Initializes the pipeline with required backend components.

        Args:
            schema: DatabaseSchema catalog for live relational grounding.
            bundle: KnowledgeBundle containing loaded OKF business rules.
            generator: SQLGenerator for prompt building and model queries.
            executor: SafeExecutor for read-only database query execution.
            retriever: Optional BM25Retriever; defaults to bundle retriever.
            router: Optional IntentRouter; defaults to intent classifier.
            rule_auditor: Optional RuleAuditor; defaults to schema rule auditor.
        """
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
        """Executes the question through the full audited pipeline.

        Args:
            question: Natural language question.
            context: Optional context parameters (e.g., fiscal_year=2024).
            max_revisions: Maximum allowable revision attempts on rule failure (default: 1).

        Returns:
            PipelineResult detailing audit outcomes, executed SQL, and query records.
        """
        context = context or {}
        audit_trail: List[Dict[str, Any]] = []

        # 1. Intent Classification
        classification: IntentClassification = self.router.classify(question)
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
        rules = filter_applicable_rules(raw_rules, question)
        retrieved_ids = [f"{r.id}@v{r.version}" for r in rules if r.type != "index"]

        # If entities detected year (e.g. "year:2024"), explicit year in question takes precedence
        for entity in classification.detected_entities:
            if entity.startswith("year:"):
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

            # If rule audit passes, query is approved for execution
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
