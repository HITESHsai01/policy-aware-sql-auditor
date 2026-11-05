"""
Policy-Aware SQL Auditor Package.

A deterministic, local-first text-to-SQL system that audits queries against
versioned corporate compliance policies and safety guardrails.

Core 7-Stage Architecture:
1. Intent Routing (`router.py`): Classifies questions into operational intents (metric queries,
   policy checks, ambiguous queries, or unsupported domains).
2. Lexical Retrieval (`retrieval.py`): Retrieves versioned Open Knowledge Format (OKF) concepts
   and policies using pure-Python Okapi BM25 scoring.
3. Grounded Prompt & Generation (`sql_generator.py`): Grounds LLM generation in live database
   schemas and mandatory compliance rules.
4. Deterministic AST Guardrails (`sql_guardrails.py`): Enforces single-statement SELECT-only
   safety and schema allowlists using SQLGlot AST inspection.
5. Semantic Rule Auditing (`rule_auditor.py`): Validates that mandatory filters, date boundaries,
   and joins are present while blocking forbidden proxy columns.
6. Revision Loop (`pipeline.py`): Feeds AST rule audit failures back to the generator for automated
   single-turn self-correction.
7. Safe Read-Only Execution (`executor.py`): Executes approved queries against SQLite with
   wall-clock timeouts and row limits.
Response Synthesis (`answer_builder.py`): Formulates natural, conversational explanations
grounded in corporate governance policies.
Audit Logging (`audit_log.py`): Persists full query traces and evaluation diagnostics to SQLite.
"""

from sql_auditor.answer_builder import AnswerBuilder, StructuredAnswer
from sql_auditor.audit_log import AuditLogger, AuditRecord
from sql_auditor.executor import ExecutionResult, SafeExecutor, execute_read_only
from sql_auditor.knowledge_loader import (
    ConceptDefinition,
    ForbiddenSubstitute,
    KnowledgeBundle,
    KnowledgeValidationError,
    RequiredFilter,
    RequiredJoin,
    load_knowledge_bundle,
)
from sql_auditor.pipeline import AuditorPipeline, PipelineResult
from sql_auditor.retrieval import BM25Retriever, ScoredConcept, tokenize
from sql_auditor.router import IntentClassification, IntentRouter, IntentType
from sql_auditor.rule_auditor import (
    AuditStatus,
    RuleAuditResult,
    RuleAuditor,
    RuleViolation,
)
from sql_auditor.schema_inspector import (
    ColumnInfo,
    DatabaseSchema,
    ForeignKeyInfo,
    TableInfo,
    inspect_schema,
)
from sql_auditor.sql_generator import (
    BaseLLMBackend,
    GenerationResult,
    MockGeneratorBackend,
    OllamaBackend,
    SQLGenerator,
)
from sql_auditor.sql_guardrails import GuardrailResult, validate_sql

__all__ = [
    # Schema inspection
    "ColumnInfo",
    "ForeignKeyInfo",
    "TableInfo",
    "DatabaseSchema",
    "inspect_schema",
    # Guardrails
    "GuardrailResult",
    "validate_sql",
    # Executor
    "ExecutionResult",
    "SafeExecutor",
    "execute_read_only",
    # Knowledge loader
    "ConceptDefinition",
    "KnowledgeBundle",
    "KnowledgeValidationError",
    "RequiredFilter",
    "RequiredJoin",
    "ForbiddenSubstitute",
    "load_knowledge_bundle",
    # Retrieval
    "BM25Retriever",
    "ScoredConcept",
    "tokenize",
    # Router
    "IntentType",
    "IntentClassification",
    "IntentRouter",
    # SQL Generator
    "BaseLLMBackend",
    "MockGeneratorBackend",
    "OllamaBackend",
    "SQLGenerator",
    "GenerationResult",
    # Rule Auditor
    "AuditStatus",
    "RuleViolation",
    "RuleAuditResult",
    "RuleAuditor",
    # Pipeline
    "AuditorPipeline",
    "PipelineResult",
    # Answer Builder
    "AnswerBuilder",
    "StructuredAnswer",
    # Audit Logger
    "AuditLogger",
    "AuditRecord",
]
