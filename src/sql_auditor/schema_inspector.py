"""
Schema Inspector module.

Extracts table names, columns, data types, primary keys, and foreign keys
from the live SQLite database, and exposes an in-memory catalog for AST
guardrails and prompt generation.
"""

from dataclasses import dataclass, field
from pathlib import Path
import sqlite3
from typing import Optional

try:
    from sql_auditor.config import DEFAULT_DB_PATH
except ImportError:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from sql_auditor.config import DEFAULT_DB_PATH


@dataclass
class ColumnInfo:
    name: str
    data_type: str
    is_pk: bool = False
    not_null: bool = False


@dataclass
class ForeignKeyInfo:
    from_column: str
    target_table: str
    target_column: str
    on_delete: str = "NO ACTION"


@dataclass
class TableInfo:
    name: str
    columns: dict[str, ColumnInfo] = field(default_factory=dict)
    foreign_keys: list[ForeignKeyInfo] = field(default_factory=list)

    def has_column(self, column_name: str) -> bool:
        return column_name.lower() in self.columns


@dataclass
class DatabaseSchema:
    tables: dict[str, TableInfo] = field(default_factory=dict)

    def has_table(self, table_name: str) -> bool:
        return table_name.lower() in self.tables

    def get_table(self, table_name: str) -> Optional[TableInfo]:
        return self.tables.get(table_name.lower())

    def has_column(self, table_name: str, column_name: str) -> bool:
        tbl = self.get_table(table_name)
        return tbl is not None and tbl.has_column(column_name)

    def to_prompt_str(self) -> str:
        """Returns a compact textual schema representation suitable for prompts."""
        lines = []
        for table_name in sorted(self.tables.keys()):
            table = self.tables[table_name]
            cols = [f"{col.name} {col.data_type}" for col in table.columns.values()]
            lines.append(f"{table.name}({', '.join(cols)})")
        return "\n".join(lines)


def inspect_schema(db_path: Path = DEFAULT_DB_PATH) -> DatabaseSchema:
    """Connects to SQLite in read-only mode and inspects all tables and columns."""
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
