"""
Schema Inspector Module for Policy-Aware SQL Auditor.

Connects to the SQLite database in strict read-only mode to extract metadata:
- Table names and column definitions (types, nullability, primary key constraints)
- Foreign key relationships and referential integrity actions
- Exposes an in-memory schema catalog used for prompt grounding and AST guardrail checks.
"""

from dataclasses import dataclass, field
from pathlib import Path
import sqlite3
from typing import Dict, List, Optional

from sql_auditor.config import DEFAULT_DB_PATH


@dataclass
class ColumnInfo:
    """Metadata describing a single table column.

    Attributes:
        name: Column identifier as defined in the SQLite schema.
        data_type: Declared SQLite affinity / data type (e.g., 'TEXT', 'INTEGER', 'NUMERIC').
        is_pk: True if column is part of the primary key constraint.
        not_null: True if column has a NOT NULL constraint.
    """

    name: str
    data_type: str
    is_pk: bool = False
    not_null: bool = False


@dataclass
class ForeignKeyInfo:
    """Metadata describing a foreign key relationship between tables.

    Attributes:
        from_column: Column name in the referencing table.
        target_table: Referenced target table name.
        target_column: Referenced column name in target table.
        on_delete: Referential action on delete (e.g., 'CASCADE', 'NO ACTION', 'RESTRICT').
    """

    from_column: str
    target_table: str
    target_column: str
    on_delete: str = "NO ACTION"


@dataclass
class TableInfo:
    """Metadata catalog for a single database table.

    Attributes:
        name: Canonical table identifier.
        columns: Dictionary mapping lowercased column names to ColumnInfo descriptors.
        foreign_keys: List of outgoing foreign key constraints defined on this table.
    """

    name: str
    columns: Dict[str, ColumnInfo] = field(default_factory=dict)
    foreign_keys: List[ForeignKeyInfo] = field(default_factory=list)

    def has_column(self, column_name: str) -> bool:
        """Checks if a column exists in the table (case-insensitive).

        Args:
            column_name: Name of the column to verify.

        Returns:
            True if the column exists in this table, False otherwise.
        """
        return column_name.lower() in self.columns


@dataclass
class DatabaseSchema:
    """In-memory representation of the complete SQLite database schema catalog.

    Attributes:
        tables: Dictionary mapping lowercased table names to TableInfo descriptors.
    """

    tables: Dict[str, TableInfo] = field(default_factory=dict)

    def has_table(self, table_name: str) -> bool:
        """Checks if a table exists in the database schema (case-insensitive).

        Args:
            table_name: Name of the table to verify.

        Returns:
            True if the table exists, False otherwise.
        """
        return table_name.lower() in self.tables

    def get_table(self, table_name: str) -> Optional[TableInfo]:
        """Retrieves TableInfo descriptor for a table name (case-insensitive).

        Args:
            table_name: Table identifier to fetch.

        Returns:
            TableInfo if found, None otherwise.
        """
        return self.tables.get(table_name.lower())

    def has_column(self, table_name: str, column_name: str) -> bool:
        """Checks if a specific column exists within a specified table.

        Args:
            table_name: Name of the table.
            column_name: Name of the column.

        Returns:
            True if both table and column exist, False otherwise.
        """
        tbl = self.get_table(table_name)
        return tbl is not None and tbl.has_column(column_name)

    def to_prompt_str(self) -> str:
        """Formats a compact, deterministic textual schema representation suitable for LLM prompts.

        Returns:
            Formatted multiline string where each line represents `table(col1 TYPE, col2 TYPE)`.
        """
        lines = []
        for table_name in sorted(self.tables.keys()):
            table = self.tables[table_name]
            cols = [f"{col.name} {col.data_type}" for col in table.columns.values()]
            lines.append(f"{table.name}({', '.join(cols)})")
        return "\n".join(lines)


def inspect_schema(db_path: Path = DEFAULT_DB_PATH) -> DatabaseSchema:
    """Connects to SQLite in read-only mode and inspects all user tables, columns, and foreign keys.

    Args:
        db_path: Filesystem path to the SQLite database file.

    Returns:
        DatabaseSchema populated with all user tables, columns, and relationships.

    Raises:
        FileNotFoundError: If the specified SQLite database file does not exist.
    """
    if not db_path.exists():
        raise FileNotFoundError(f"Database file does not exist: {db_path}")

    uri = f"file:{db_path.resolve()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        cur = conn.cursor()

        # 1. Fetch all user tables (ignore internal sqlite_* tables)
        cur.execute(
            "SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name;"
        )
        table_names = [row[0] for row in cur.fetchall()]

        schema = DatabaseSchema()

        for table_name in table_names:
            table_info = TableInfo(name=table_name)

            # 2. Fetch column definitions: (cid, name, type, notnull, dflt_value, pk)
            cur.execute(f"PRAGMA table_info('{table_name}');")
            for col_row in cur.fetchall():
                col_name = col_row[1]
                col_type = col_row[2]
                not_null = bool(col_row[3])
                is_pk = bool(col_row[5])

                column_info = ColumnInfo(
                    name=col_name,
                    data_type=col_type,
                    is_pk=is_pk,
                    not_null=not_null,
                )
                table_info.columns[col_name.lower()] = column_info

            # 3. Fetch foreign keys: (id, seq, table, from, to, on_update, on_delete, match)
            cur.execute(f"PRAGMA foreign_key_list('{table_name}');")
            for fk_row in cur.fetchall():
                fk_info = ForeignKeyInfo(
                    from_column=fk_row[3],
                    target_table=fk_row[2],
                    target_column=fk_row[4],
                    on_delete=fk_row[6],
                )
                table_info.foreign_keys.append(fk_info)

            schema.tables[table_name.lower()] = table_info

        return schema
    finally:
        conn.close()


if __name__ == "__main__":
    schema = inspect_schema()
    print("Extracted Database Schema:")
    print(schema.to_prompt_str())
