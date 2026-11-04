"""Policy-Aware SQL Auditor package."""

from sql_auditor.schema_inspector import DatabaseSchema, inspect_schema
from sql_auditor.sql_guardrails import GuardrailResult, validate_sql
from sql_auditor.executor import ExecutionResult, SafeExecutor, execute_read_only
from sql_auditor.knowledge_loader import (
    ConceptDefinition,
    KnowledgeBundle,
    KnowledgeValidationError,
    RequiredFilter,
    RequiredJoin,
    ForbiddenSubstitute,
    load_knowledge_bundle,
)
from sql_auditor.retrieval import BM25Retriever, ScoredConcept
from sql_auditor.router import IntentType, IntentClassification, IntentRouter
from sql_auditor.sql_generator import (
    BaseLLMBackend,
    MockGeneratorBackend,
    OllamaBackend,
    SQLGenerator,
    GenerationResult,
)
from sql_auditor.rule_auditor import (
    AuditStatus,
    RuleViolation,
    RuleAuditResult,
    RuleAuditor,
)
from sql_auditor.pipeline import AuditorPipeline, PipelineResult

__all__ = [
    "DatabaseSchema",
    "inspect_schema",
    "GuardrailResult",
    "validate_sql",
    "ExecutionResult",
    "SafeExecutor",
    "execute_read_only",
    "ConceptDefinition",
    "KnowledgeBundle",
    "KnowledgeValidationError",
    "RequiredFilter",
    "RequiredJoin",
    "ForbiddenSubstitute",
    "load_knowledge_bundle",
    "BM25Retriever",
    "ScoredConcept",
    "IntentType",
    "IntentClassification",
    "IntentRouter",
    "BaseLLMBackend",
    "MockGeneratorBackend",
    "OllamaBackend",
    "SQLGenerator",
    "GenerationResult",
    "AuditStatus",
    "RuleViolation",
    "RuleAuditResult",
    "RuleAuditor",
    "AuditorPipeline",
    "PipelineResult",
]
