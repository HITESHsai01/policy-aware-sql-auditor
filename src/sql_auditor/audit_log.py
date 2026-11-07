"""
Audit Trail Logger Module for Policy-Aware SQL Auditor.

Records comprehensive diagnostic audit logs for every query evaluation into a dedicated
SQLite audit table (`audit_logs`), capturing request timestamps, intent classification,
retrieved rules, candidate SQL, guardrail results, compliance check diagnostics,
and execution telemetry without leaking secrets or raw internal stack traces.
"""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import time
from typing import Any, Dict, List, Optional
import uuid

from sql_auditor.config import DEFAULT_AUDIT_DB_PATH
from sql_auditor.pipeline import PipelineResult


@dataclass
class AuditRecord:
    """Persistent audit entry recording full evaluation telemetry for a query.

    Attributes:
        request_id: Globally unique identifier for this audit event.
        timestamp: ISO 8601 UTC timestamp string.
        question: Original natural-language question submitted by user.
        intent: Classified operational intent category.
        executed: True if the query was verified and executed; False otherwise.
        final_sql: Candidate or approved SQL query text.
        retrieved_rules: List of retrieved OKF concept tags ('<id>@v<version>').
        guardrail_status: Status code: 'PASS', 'FAIL', or 'SKIPPED'.
        guardrail_error: Error message if rejected by AST guardrails.
        rule_audit_status: Status code: 'PASS', 'FAIL', or 'SKIPPED'.
        rule_violations: List of violation descriptions if rule audit failed.
        revisions_attempted: Number of self-correction revision cycles executed.
        execution_time_ms: Query execution duration in milliseconds.
        row_count: Number of records returned by the query.
        error_message: Error string if execution or validation failed.
    """

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
        """Serializes the audit record to a dictionary."""
        return asdict(self)


class AuditLogger:
    """Manages persistent SQLite logging and retrieval of query audit records."""

    def __init__(self, db_path: Path = DEFAULT_AUDIT_DB_PATH):
        """Initializes the audit logger and ensures database tables and indexes exist.

        Args:
            db_path: Path to SQLite database hosting the audit_logs table.
        """
        self.db_path = Path(db_path)
        self._init_db()

    def _get_connection(self, timeout: float = 10.0) -> sqlite3.Connection:
        """Creates a SQLite connection with configured busy timeout and WAL optimization.

        Args:
            timeout: Connection busy wait timeout in seconds (default: 10.0).

        Returns:
            Open sqlite3.Connection instance with busy_timeout configured.
        """
        conn = sqlite3.connect(self.db_path, timeout=timeout)
        conn.execute("PRAGMA busy_timeout = 5000;")
        return conn

    def _init_db(self) -> None:
        """Initializes the audit_logs table, WAL mode, and performance indexes."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._get_connection(timeout=10.0)
        try:
            cur = conn.cursor()
            # Enable Write-Ahead Logging (WAL) mode and busy timeout to prevent lock contention
            cur.execute("PRAGMA journal_mode = WAL;")
            cur.execute("PRAGMA busy_timeout = 5000;")
            cur.execute("PRAGMA synchronous = NORMAL;")
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
        """Constructs an AuditRecord from a PipelineResult and persists it to SQLite.

        Args:
            result: Completed PipelineResult instance from pipeline execution.
            request_id: Optional custom request UUID; generated automatically if None.

        Returns:
            The persisted AuditRecord instance.
        """
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

        # Write to SQLite with retry protection for transient locks
        max_attempts = 3
        for attempt in range(max_attempts):
            conn = self._get_connection(timeout=10.0)
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
                break
            except sqlite3.OperationalError as e:
                if "locked" in str(e).lower() and attempt < max_attempts - 1:
                    time.sleep(0.1 * (attempt + 1))
                    continue
                raise
            finally:
                conn.close()

        return record

    def get_recent_records(self, limit: int = 50) -> List[AuditRecord]:
        """Retrieves most recent audit logs ordered by timestamp descending.

        Args:
            limit: Maximum number of audit records to retrieve (default: 50).

        Returns:
            List of AuditRecord instances.
        """
        conn = self._get_connection(timeout=10.0)
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
        """Retrieves a single audit record by request ID.

        Args:
            request_id: Unique request UUID string.

        Returns:
            AuditRecord if found, None otherwise.
        """
        conn = self._get_connection(timeout=10.0)
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
