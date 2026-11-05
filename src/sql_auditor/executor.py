"""
Safe Read-Only SQLite Executor Module for Policy-Aware SQL Auditor.

Executes queries against SQLite in read-only mode (`mode=ro`) with strict safety controls:
- Read-only URI enforcement
- Wall-clock execution timeout using SQLite virtual machine progress handler
- Row truncation limits to prevent memory exhaustion
- Foreign key constraints enabled
- Sanitized error reporting without leaking raw internal stack traces
"""

from dataclasses import dataclass, field
from pathlib import Path
import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple

from sql_auditor.config import (
    DEFAULT_DB_PATH,
    DEFAULT_ROW_LIMIT,
    DEFAULT_TIMEOUT_SECONDS,
)


@dataclass
class ExecutionResult:
    """Encapsulates the result of executing a read-only SQLite query.

    Attributes:
        success: True if the query completed without errors; False on error or timeout.
        columns: List of projected column names in the result set.
        rows: List of row dictionaries mapping column names to cell values.
        row_count: Number of records returned in the rows list.
        truncated: True if database output exceeded max_rows and was capped.
        execution_time_ms: Measured elapsed query execution time in milliseconds.
        error_message: Sanitized error description if execution failed.
    """

    success: bool
    columns: List[str] = field(default_factory=list)
    rows: List[Dict[str, Any]] = field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    execution_time_ms: float = 0.0
    error_message: Optional[str] = None


class SafeExecutor:
    """Safe read-only query executor for SQLite databases.

    Features:
    - Guaranteed read-only connection via URI mode=ro.
    - Interrupts long-running queries via sqlite3.Connection.set_progress_handler.
    - Caps result rows to prevent memory exhaustion.
    """

    def __init__(
        self,
        db_path: Path = DEFAULT_DB_PATH,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_rows: int = DEFAULT_ROW_LIMIT,
    ):
        """Initializes the executor with database path, timeout, and row limits.

        Args:
            db_path: Path to the SQLite database file.
            timeout_seconds: Execution timeout limit in seconds.
            max_rows: Maximum records returned before truncation.
        """
        self.db_path = Path(db_path)
        self.timeout_seconds = timeout_seconds
        self.max_rows = max_rows

    def execute(
        self,
        sql: str,
        params: Optional[Tuple[Any, ...]] = None,
        max_rows: Optional[int] = None,
        timeout_seconds: Optional[float] = None,
    ) -> ExecutionResult:
        """Executes a SQL query in read-only mode with timeout and row-limit safety.

        Args:
            sql: The SQL query string to execute.
            params: Optional tuple of query parameters.
            max_rows: Optional override for maximum rows to fetch.
            timeout_seconds: Optional override for execution timeout in seconds.

        Returns:
            ExecutionResult containing query output or sanitized error description.
        """
        effective_timeout = timeout_seconds if timeout_seconds is not None else self.timeout_seconds
        effective_max_rows = max_rows if max_rows is not None else self.max_rows

        if not self.db_path.exists():
            return ExecutionResult(
                success=False,
                error_message=f"Database file does not exist: {self.db_path}",
            )

        # Open SQLite in read-only mode using URI
        uri = f"file:{self.db_path.resolve()}?mode=ro"
        start_time = time.perf_counter()

        try:
            conn = sqlite3.connect(uri, uri=True, timeout=effective_timeout)
        except sqlite3.Error as e:
            return ExecutionResult(
                success=False,
                error_message=f"Failed to open database connection: {type(e).__name__}: {str(e)}",
            )

        try:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()

            # Enable foreign key enforcement
            cur.execute("PRAGMA foreign_keys = ON;")

            # Progress handler for deterministic wall-clock timeout check
            deadline = time.perf_counter() + effective_timeout

            def progress_callback() -> int:
                # Return non-zero to interrupt query if deadline exceeded
                if time.perf_counter() > deadline:
                    return 1
                return 0

            # Check every 100 SQLite virtual machine opcodes
            conn.set_progress_handler(progress_callback, 100)

            # Execute query
            if params:
                cur.execute(sql, params)
            else:
                cur.execute(sql)

            # Retrieve column names
            columns = [col[0] for col in cur.description] if cur.description else []

            # Fetch rows with row cap + 1 to detect truncation
            raw_rows = cur.fetchmany(effective_max_rows + 1)
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0

            truncated = len(raw_rows) > effective_max_rows
            final_rows = raw_rows[:effective_max_rows]

            # Convert sqlite3.Row objects to dictionaries
            dict_rows = [dict(row) for row in final_rows]

            return ExecutionResult(
                success=True,
                columns=columns,
                rows=dict_rows,
                row_count=len(dict_rows),
                truncated=truncated,
                execution_time_ms=round(elapsed_ms, 2),
            )

        except sqlite3.OperationalError as oe:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            err_msg = str(oe)
            if "interrupted" in err_msg.lower():
                return ExecutionResult(
                    success=False,
                    execution_time_ms=round(elapsed_ms, 2),
                    error_message=f"Query timed out after exceeding {effective_timeout:.2f} seconds.",
                )
            return ExecutionResult(
                success=False,
                execution_time_ms=round(elapsed_ms, 2),
                error_message=f"Execution error: {err_msg}",
            )
        except Exception as e:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return ExecutionResult(
                success=False,
                execution_time_ms=round(elapsed_ms, 2),
                error_message=f"Execution failed: {type(e).__name__}: {str(e)}",
            )
        finally:
            conn.set_progress_handler(None, 0)
            conn.close()


def execute_read_only(
    sql: str,
    db_path: Path = DEFAULT_DB_PATH,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_rows: int = DEFAULT_ROW_LIMIT,
) -> ExecutionResult:
    """Convenience helper to execute a query with default read-only settings.

    Args:
        sql: Query string to execute.
        db_path: Path to database.
        timeout_seconds: Wall-clock timeout.
        max_rows: Maximum records returned.

    Returns:
        ExecutionResult containing results or failure diagnostic.
    """
    executor = SafeExecutor(
        db_path=db_path,
        timeout_seconds=timeout_seconds,
        max_rows=max_rows,
    )
    return executor.execute(sql)
