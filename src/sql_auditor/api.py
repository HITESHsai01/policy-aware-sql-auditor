"""
FastAPI REST API Service for Policy-Aware SQL Auditor.

Exposes REST endpoints:
- POST /ask: Evaluates questions, generates compliant SQL, audits rules, and executes read-only.
- GET /health: Healthcheck, database status, and catalog readiness.
- GET /audit-logs: Returns recent diagnostic audit records.
- GET /rules: Returns active Open Knowledge Format (OKF) concept definitions.
"""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from sql_auditor.answer_builder import AnswerBuilder, StructuredAnswer
from sql_auditor.audit_log import AuditLogger, AuditRecord
from sql_auditor.config import DEFAULT_DB_PATH, KNOWLEDGE_DIR
from sql_auditor.executor import SafeExecutor
from sql_auditor.knowledge_loader import KnowledgeBundle, load_knowledge_bundle
from sql_auditor.pipeline import AuditorPipeline, PipelineResult
from sql_auditor.schema_inspector import DatabaseSchema, inspect_schema
from sql_auditor.sql_generator import MockGeneratorBackend, SQLGenerator


# Request / Response Schemas
class AskRequest(BaseModel):
    """Payload schema for submitting a natural language query."""

    question: str = Field(..., description="Natural language question to ask the database.")
    context: Optional[Dict[str, Any]] = Field(
        default=None, description="Optional context parameters like fiscal_year."
    )


class AskResponse(BaseModel):
    """Response schema returned by the /ask query endpoint."""

    status: str = Field(..., description="Evaluation status (success, rejected_rule_violation, etc.).")
    answer_summary: str = Field(..., description="Natural language answer summary.")
    sql_query: Optional[str] = Field(default=None, description="Executed or candidate SQL query.")
    columns: List[str] = Field(default_factory=list, description="Projected column names.")
    rows: List[Dict[str, Any]] = Field(default_factory=list, description="Returned result rows.")
    row_count: int = Field(default=0, description="Total records returned.")
    truncated: bool = Field(default=False, description="Whether row limit was reached.")
    cited_rules: List[str] = Field(default_factory=list, description="Identifiers of rules applied.")
    revisions_attempted: int = Field(default=0, description="Number of automated revisions.")
    clarification_prompt: Optional[str] = Field(default=None, description="Clarification message if needed.")
    diagnostics: Dict[str, Any] = Field(default_factory=dict, description="Internal diagnostic traces.")
    request_id: Optional[str] = Field(default=None, description="Unique audit trace identifier.")
    explanation: Optional[str] = Field(default=None, description="Detailed conversational explanation.")
    policy_justifications: List[Dict[str, Any]] = Field(
        default_factory=list, description="Structured policy explanations."
    )


class HealthResponse(BaseModel):
    """Response schema returned by the /health readiness probe."""

    status: str = Field(..., description="System operational status ('ok').")
    database: str = Field(..., description="Path to active SQLite database.")
    tables_count: int = Field(..., description="Number of user tables discovered.")
    tables: List[str] = Field(..., description="Alphabetical list of table names.")
    concepts_loaded: int = Field(..., description="Count of loaded OKF concepts.")
    timestamp: str = Field(..., description="ISO 8601 UTC timestamp of healthcheck.")


def create_app(
    pipeline: Optional[AuditorPipeline] = None,
    logger: Optional[AuditLogger] = None,
    db_path: Path = DEFAULT_DB_PATH,
    knowledge_dir: Path = KNOWLEDGE_DIR,
) -> FastAPI:
    """Factory function to instantiate the FastAPI app with dependency injection.

    Args:
        pipeline: Optional pre-configured AuditorPipeline instance.
        logger: Optional AuditLogger instance.
        db_path: Path to the SQLite database file.
        knowledge_dir: Path to directory containing OKF concept markdown files.

    Returns:
        Configured FastAPI application instance.
    """
    # Initialize default dependencies if not supplied
    if pipeline is None:
        schema = inspect_schema(db_path=db_path)
        bundle = load_knowledge_bundle(knowledge_dir=knowledge_dir, schema=schema)
        executor = SafeExecutor(db_path=db_path)
        backend = MockGeneratorBackend()
        generator = SQLGenerator(backend=backend, schema=schema)
        pipeline = AuditorPipeline(
            schema=schema,
            bundle=bundle,
            generator=generator,
            executor=executor,
        )

    if logger is None:
        logger = AuditLogger(db_path=db_path)

    app = FastAPI(
        title="Policy-Aware SQL Auditor API",
        version="0.1.0",
        description="Local-first text-to-SQL system that deterministically audits queries against versioned compliance rules.",
    )

    # Store in app state
    app.state.pipeline = pipeline
    app.state.logger = logger
    app.state.db_path = db_path

    @app.get("/health", response_model=HealthResponse)
    async def health_check() -> HealthResponse:
        """Health check endpoint reporting database connectivity and loaded rule metrics."""
        pipe: AuditorPipeline = app.state.pipeline
        schema: DatabaseSchema = pipe.schema
        tables = list(schema.tables.keys())
        return HealthResponse(
            status="ok",
            database=str(app.state.db_path),
            tables_count=len(tables),
            tables=sorted(tables),
            concepts_loaded=len(pipe.bundle.concepts),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    @app.post("/ask", response_model=AskResponse)
    async def ask_question(request: AskRequest) -> AskResponse:
        """Evaluates a user question through the audited pipeline and returns a structured response."""
        pipe: AuditorPipeline = app.state.pipeline
        audit_log: AuditLogger = app.state.logger

        # Execute query through full audited pipeline
        result: PipelineResult = pipe.run(
            question=request.question,
            context=request.context,
        )

        # Build consumer-facing answer
        answer: StructuredAnswer = AnswerBuilder.build_answer(result)

        # Persist audit record to SQLite
        audit_rec: AuditRecord = audit_log.log_result(result)

        return AskResponse(
            status=answer.status,
            answer_summary=answer.answer_summary,
            sql_query=answer.sql_query,
            columns=answer.columns,
            rows=answer.rows,
            row_count=answer.row_count,
            truncated=answer.truncated,
            cited_rules=answer.cited_rules,
            revisions_attempted=answer.revisions_attempted,
            clarification_prompt=answer.clarification_prompt,
            diagnostics=answer.diagnostics,
            request_id=audit_rec.request_id,
            explanation=answer.explanation,
            policy_justifications=answer.policy_justifications,
        )

    @app.get("/audit-logs", response_model=List[Dict[str, Any]])
    async def get_audit_logs(limit: int = Query(default=20, ge=1, le=100)) -> List[Dict[str, Any]]:
        """Retrieves recent query audit records from persistent SQLite audit storage."""
        audit_log: AuditLogger = app.state.logger
        records = audit_log.get_recent_records(limit=limit)
        return [r.to_dict() for r in records]

    @app.get("/rules", response_model=List[Dict[str, Any]])
    async def list_rules() -> List[Dict[str, Any]]:
        """Lists active Open Knowledge Format (OKF) business compliance rules and constraints."""
        pipe: AuditorPipeline = app.state.pipeline
        concepts = pipe.bundle.get_all()
        return [
            {
                "id": c.id,
                "version": c.version,
                "type": c.type,
                "title": c.title,
                "description": c.description,
                "tables": c.tables,
                "required_filters": [
                    {"column": f.column, "operator": f.operator, "value": f.value, "type": f.type}
                    for f in c.required_filters
                ],
                "forbidden_substitutes": [
                    {"column": s.column, "reason": s.reason}
                    for s in c.forbidden_substitutes
                ],
            }
            for c in concepts
            if c.type != "index"
        ]

    return app


# Default application instance
app = create_app()
