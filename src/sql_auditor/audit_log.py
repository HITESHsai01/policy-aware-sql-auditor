"""
Audit Trail Logger Module.

Records full diagnostic audit logs for every query evaluation into a dedicated
SQLite audit table (and optional JSONL sink), capturing request timestamps,
retrieved rules, candidate SQL, guardrail results, compliance check diagnostics,
and execution stats without leaking secrets or raw stack traces.
"""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional
import uuid

try:
    from sql_auditor.config import DEFAULT_DB_PATH
    from sql_auditor.pipeline import PipelineResult
except ImportError:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from sql_auditor.config import DEFAULT_DB_PATH
    from sql_auditor.pipeline import PipelineResult


@dataclass
class AuditRecord:
    request_id: str
    timestamp: str
    question: str
    intent: str
    executed: bool
    final_sql: Optional[str]
    retrieved_rules: List[str]
    guardrail_status: str  # PASS, FAIL, SKIPPED
    guardrail_error: Optional[str]
    rule_audit_status: str  # PASS, FAIL, SKIPPED
    rule_violations: List[str]
    revisions_attempted: int
    execution_time_ms: float
    row_count: int
    error_message: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class AuditLogger:
    """Manages persistent SQLite logging of audit records."""

    def __init__(self, db_path: Path = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self._init_db()

    def _init_db(self) -> None:
        """Initializes the audit_logs table if it does not exist."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS audit_logs (
                    request_id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    question TEXT NOT NULL,
                    intent TEXT NOT NULL,
                    executed INTEGER NOT NULL,
                    final_sql TEXT,
                    retrieved_rules TEXT NOT NULL,
                    guardrail_status TEXT NOT NULL,
                    guardrail_error TEXT,
                    rule_audit_status TEXT NOT NULL,
                    rule_violations TEXT NOT NULL,
                    revisions_attempted INTEGER NOT NULL,
                    execution_time_ms REAL NOT NULL,
                    row_count INTEGER NOT NULL,
                    error_message TEXT
                );
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_logs(timestamp);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_audit_executed ON audit_logs(executed);")
            conn.commit()
        finally:
            conn.close()

    def log_result(
        self,
        result: PipelineResult,
        request_id: Optional[str] = None,
    ) -> AuditRecord:
        """Constructs an AuditRecord from a PipelineResult and persists it to SQLite."""
        req_id = request_id or str(uuid.uuid4())
        ts = datetime.now(timezone.utc).isoformat()

        # Guardrail status
        if result.guardrail_result is not None:
            guardrail_status = "PASS" if result.guardrail_result.is_valid else "FAIL"
            guardrail_error = result.guardrail_result.error_message
        else:
            guardrail_status = "SKIPPED"
            guardrail_error = None

        # Rule audit status
        if result.rule_audit_result is not None:
            rule_status = result.rule_audit_result.status.value
            violations = [v.message for v in result.rule_audit_result.violations]
        else:
            rule_status = "SKIPPED"
            violations = []

        # Execution stats
        exec_ms = result.execution_result.execution_time_ms if result.execution_result else 0.0
        row_cnt = result.execution_result.row_count if result.execution_result else 0

        record = AuditRecord(
            request_id=req_id,
            timestamp=ts,
            question=result.question,
            intent=result.intent.value,
            executed=result.executed,
            final_sql=result.final_sql,
            retrieved_rules=result.retrieved_rule_ids,
            guardrail_status=guardrail_status,
            guardrail_error=guardrail_error,
            rule_audit_status=rule_status,
            rule_violations=violations,
            revisions_attempted=result.revisions_attempted,
            execution_time_ms=exec_ms,
            row_count=row_cnt,
            error_message=result.error_message,
        )

        # Write to SQLite
        conn = sqlite3.connect(self.db_path)
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO audit_logs (
                    request_id, timestamp, question, intent, executed,
                    final_sql, retrieved_rules, guardrail_status, guardrail_error,
                    rule_audit_status, rule_violations, revisions_attempted,
                    execution_time_ms, row_count, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    record.request_id,
                    record.timestamp,
                    record.question,
                    record.intent,
                    1 if record.executed else 0,
                    record.final_sql,
                    json.dumps(record.retrieved_rules),
                    record.guardrail_status,
                    record.guardrail_error,
                    record.rule_audit_status,
                    json.dumps(record.rule_violations),
                    record.revisions_attempted,
                    record.execution_time_ms,
                    record.row_count,
                    record.error_message,
                ),
            )
            conn.commit()
        finally:
            conn.close()

        return record

    def get_recent_records(self, limit: int = 50) -> List[AuditRecord]:
        """Retrieves most recent audit logs ordered by timestamp descending."""
        conn = sqlite3.connect(self.db_path)
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT request_id, timestamp, question, intent, executed,
                       final_sql, retrieved_rules, guardrail_status, guardrail_error,
                       rule_audit_status, rule_violations, revisions_attempted,
                       execution_time_ms, row_count, error_message
                FROM audit_logs
                ORDER BY timestamp DESC
                LIMIT ?;
                """,
                (limit,),
            )
            records = []
            for row in cur.fetchall():
                records.append(
                    AuditRecord(
                        request_id=row[0],
                        timestamp=row[1],
                        question=row[2],
                        intent=row[3],
                        executed=bool(row[4]),
                        final_sql=row[5],
                        retrieved_rules=json.loads(row[6]),
                        guardrail_status=row[7],
                        guardrail_error=row[8],
                        rule_audit_status=row[9],
                        rule_violations=json.loads(row[10]),
                        revisions_attempted=row[11],
                        execution_time_ms=row[12],
                        row_count=row[13],
                        error_message=row[14],
                    )
                )
            return records
        finally:
            conn.close()

    def get_record(self, request_id: str) -> Optional[AuditRecord]:
        """Retrieves a single audit record by request ID."""
        conn = sqlite3.connect(self.db_path)
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT request_id, timestamp, question, intent, executed,
                       final_sql, retrieved_rules, guardrail_status, guardrail_error,
                       rule_audit_status, rule_violations, revisions_attempted,
                       execution_time_ms, row_count, error_message
                FROM audit_logs
                WHERE request_id = ?;
                """,
                (request_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return AuditRecord(
                request_id=row[0],
                timestamp=row[1],
                question=row[2],
                intent=row[3],
                executed=bool(row[4]),
                final_sql=row[5],
                retrieved_rules=json.loads(row[6]),
                guardrail_status=row[7],
                guardrail_error=row[8],
                rule_audit_status=row[9],
                rule_violations=json.loads(row[10]),
                revisions_attempted=row[11],
                execution_time_ms=row[12],
                row_count=row[13],
                error_message=row[14],
            )
        finally:
            conn.close()
