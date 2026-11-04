"""
FastAPI REST API Service for Policy-Aware SQL Auditor.

Exposes endpoints:
- POST /ask: Evaluates questions, generates compliant SQL, audits rules, and executes read-only.
- GET /health: Healthcheck and system readiness.
- GET /audit-logs: Returns recent audit records.
- GET /rules: Returns loaded OKF concept rules.
"""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

try:
    from sql_auditor.config import DEFAULT_DB_PATH, KNOWLEDGE_DIR
    from sql_auditor.schema_inspector import DatabaseSchema, inspect_schema
    from sql_auditor.knowledge_loader import KnowledgeBundle, load_knowledge_bundle
    from sql_auditor.executor import SafeExecutor
    from sql_auditor.sql_generator import SQLGenerator, MockGeneratorBackend
    from sql_auditor.pipeline import AuditorPipeline, PipelineResult
    from sql_auditor.audit_log import AuditLogger, AuditRecord
    from sql_auditor.answer_builder import AnswerBuilder, StructuredAnswer
except ImportError:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from sql_auditor.config import DEFAULT_DB_PATH, KNOWLEDGE_DIR
    from sql_auditor.schema_inspector import DatabaseSchema, inspect_schema
    from sql_auditor.knowledge_loader import KnowledgeBundle, load_knowledge_bundle
    from sql_auditor.executor import SafeExecutor
    from sql_auditor.sql_generator import SQLGenerator, MockGeneratorBackend
    from sql_auditor.pipeline import AuditorPipeline, PipelineResult
    from sql_auditor.audit_log import AuditLogger, AuditRecord
    from sql_auditor.answer_builder import AnswerBuilder, StructuredAnswer


# Request / Response Schemas
class AskRequest(BaseModel):
    question: str = Field(..., description="Natural language question to ask the database.")
    context: Optional[Dict[str, Any]] = Field(default=None, description="Optional context parameters like fiscal_year.")


class AskResponse(BaseModel):
    status: str
    answer_summary: str
    sql_query: Optional[str] = None
    columns: List[str] = []
    rows: List[Dict[str, Any]] = []
    row_count: int = 0
    truncated: bool = False
    cited_rules: List[str] = []
    revisions_attempted: int = 0
    clarification_prompt: Optional[str] = None
    diagnostics: Dict[str, Any] = {}
    request_id: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    database: str
    tables_count: int
    tables: List[str]
    concepts_loaded: int
    timestamp: str


def create_app(
    pipeline: Optional[AuditorPipeline] = None,
    logger: Optional[AuditLogger] = None,
    db_path: Path = DEFAULT_DB_PATH,
    knowledge_dir: Path = KNOWLEDGE_DIR,
) -> FastAPI:
    """Factory function to instantiate the FastAPI app with dependency injection."""

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
    def health_check() -> HealthResponse:
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
    def ask_question(request: AskRequest) -> AskResponse:
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
        )

    @app.get("/audit-logs", response_model=List[Dict[str, Any]])
    def get_audit_logs(limit: int = Query(default=20, ge=1, le=100)) -> List[Dict[str, Any]]:
        audit_log: AuditLogger = app.state.logger
        records = audit_log.get_recent_records(limit=limit)
        return [r.to_dict() for r in records]

    @app.get("/rules", response_model=List[Dict[str, Any]])
    def list_rules() -> List[Dict[str, Any]]:
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


# Default app instance
app = create_app()
