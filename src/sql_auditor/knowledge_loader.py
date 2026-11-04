"""
Knowledge Loader and Validator for Open Knowledge Format (OKF) concepts.

Loads, parses, and validates versioned OKF concept files from the knowledge/ directory:
- Parses YAML frontmatter and Markdown bodies.
- Grounds and validates referenced tables and columns against DatabaseSchema.
- Ensures cross-references between related concepts resolve cleanly.
- Produces strongly-typed ConceptDefinition and KnowledgeBundle objects.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
import yaml

try:
    from sql_auditor.config import KNOWLEDGE_DIR
    from sql_auditor.schema_inspector import DatabaseSchema, inspect_schema
except ImportError:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from sql_auditor.config import KNOWLEDGE_DIR
    from sql_auditor.schema_inspector import DatabaseSchema, inspect_schema


@dataclass
class RequiredFilter:
    column: str
    operator: Optional[str] = "="
    value: Optional[Any] = None
    type: Optional[str] = None
    window_days: Optional[int] = None
    start_pattern: Optional[str] = None
    end_pattern: Optional[str] = None


@dataclass
class RequiredJoin:
    from_table: str
    to_table: str
    on: str


@dataclass
class ForbiddenSubstitute:
    column: str
    reason: str


@dataclass
class ConceptDefinition:
    id: str
    version: int
    type: str  # 'metric', 'policy', 'table', 'index'
    title: str
    description: str
    tags: List[str] = field(default_factory=list)
    tables: List[str] = field(default_factory=list)
    related_concepts: List[str] = field(default_factory=list)
    required_filters: List[RequiredFilter] = field(default_factory=list)
    required_joins: List[RequiredJoin] = field(default_factory=list)
    forbidden_substitutes: List[ForbiddenSubstitute] = field(default_factory=list)
    columns: List[Dict[str, Any]] = field(default_factory=list)
    body: str = ""
    file_path: Optional[Path] = None


@dataclass
class KnowledgeBundle:
    concepts: Dict[str, ConceptDefinition] = field(default_factory=dict)

    def get(self, concept_id: str) -> Optional[ConceptDefinition]:
        return self.concepts.get(concept_id)

    def list_by_type(self, concept_type: str) -> List[ConceptDefinition]:
        return [c for c in self.concepts.values() if c.type == concept_type]

    def list_by_table(self, table_name: str) -> List[ConceptDefinition]:
        tbl = table_name.lower()
        return [c for c in self.concepts.values() if tbl in [t.lower() for t in c.tables]]

    def get_all(self) -> List[ConceptDefinition]:
        return list(self.concepts.values())


class KnowledgeValidationError(Exception):
    """Raised when a knowledge concept fails schema grounding or reference validation."""
    pass


def parse_concept_file(file_path: Path) -> ConceptDefinition:
    """Parses a single Markdown file with YAML frontmatter."""
    text = file_path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise KnowledgeValidationError(f"File {file_path.name} missing opening YAML frontmatter '---'")

    parts = text.split("---", 2)
    if len(parts) < 3:
        raise KnowledgeValidationError(f"File {file_path.name} has malformed YAML frontmatter")

    yaml_text = parts[1]
    body = parts[2].strip()

    try:
        data = yaml.safe_load(yaml_text) or {}
    except Exception as e:
        raise KnowledgeValidationError(f"Failed to parse YAML frontmatter in {file_path.name}: {e}")

    # Check required fields
    for req in ("id", "version", "type", "title", "description"):
        if req not in data:
            raise KnowledgeValidationError(f"Concept in {file_path.name} missing required attribute '{req}'")

    # Parse required filters
    parsed_filters = []
    for f in data.get("required_filters", []):
        parsed_filters.append(
            RequiredFilter(
                column=f.get("column", ""),
                operator=f.get("operator", "="),
                value=f.get("value"),
                type=f.get("type"),
                window_days=f.get("window_days"),
                start_pattern=f.get("start_pattern"),
                end_pattern=f.get("end_pattern"),
            )
        )

    # Parse required joins
    parsed_joins = []
    for j in data.get("required_joins", []):
        # Note: in YAML 1.1, bare 'on:' parses as boolean True
        on_clause = j.get("on") if "on" in j else (j.get(True) or j.get("join_condition", ""))
        parsed_joins.append(
            RequiredJoin(
                from_table=j.get("from_table", ""),
                to_table=j.get("to_table", ""),
                on=str(on_clause or ""),
            )
        )

    # Parse forbidden substitutes
    parsed_substitutes = []
    for s in data.get("forbidden_substitutes", []):
        parsed_substitutes.append(
            ForbiddenSubstitute(
                column=s.get("column", ""),
                reason=s.get("reason", ""),
            )
        )

    return ConceptDefinition(
        id=data["id"],
        version=int(data["version"]),
        type=data["type"],
        title=data["title"],
        description=data["description"],
        tags=data.get("tags", []),
        tables=data.get("tables", []),
        related_concepts=data.get("related_concepts", []),
        required_filters=parsed_filters,
        required_joins=parsed_joins,
        forbidden_substitutes=parsed_substitutes,
        columns=data.get("columns", []),
        body=body,
        file_path=file_path,
    )


def load_knowledge_bundle(
    knowledge_dir: Path = KNOWLEDGE_DIR,
    schema: Optional[DatabaseSchema] = None,
    validate_references: bool = True,
) -> KnowledgeBundle:
    """
    Loads all concept markdown files from the knowledge directory and performs
    validation against the live database schema and cross-concept references.
    """
    if not knowledge_dir.exists():
        raise FileNotFoundError(f"Knowledge directory does not exist: {knowledge_dir}")

    bundle = KnowledgeBundle()
    md_files = list(knowledge_dir.rglob("*.md"))

    for f in md_files:
        concept = parse_concept_file(f)
        if concept.id in bundle.concepts:
            raise KnowledgeValidationError(f"Duplicate concept ID detected: '{concept.id}' in {f.name}")
        bundle.concepts[concept.id] = concept

    # Schema Grounding & Cross-Reference Validation
    if validate_references:
        all_ids = set(bundle.concepts.keys())

        for concept in bundle.concepts.values():
            # 1. Validate related concepts exist in bundle
            for rel in concept.related_concepts:
                if rel not in all_ids:
                    raise KnowledgeValidationError(
                        f"Concept '{concept.id}' references non-existent related concept '{rel}'"
                    )

            # 2. Schema grounding (if schema provided)
            if schema is not None:
                # Check tables
                for tbl in concept.tables:
                    if not schema.has_table(tbl):
                        raise KnowledgeValidationError(
                            f"Concept '{concept.id}' references table '{tbl}' which does not exist in schema."
                        )

                # Check columns in required filters
                for rf in concept.required_filters:
                    if rf.column and "." in rf.column:
                        tbl, col = rf.column.split(".", 1)
                        if not schema.has_column(tbl, col):
                            raise KnowledgeValidationError(
                                f"Concept '{concept.id}' filter references unknown column '{rf.column}'."
                            )

                # Check columns in forbidden substitutes
                for fs in concept.forbidden_substitutes:
                    if fs.column and "." in fs.column:
                        tbl, col = fs.column.split(".", 1)
                        if not schema.has_column(tbl, col):
                            raise KnowledgeValidationError(
                                f"Concept '{concept.id}' forbidden substitute references unknown column '{fs.column}'."
                            )

                # Check joins
                for rj in concept.required_joins:
                    if not schema.has_table(rj.from_table):
                        raise KnowledgeValidationError(
                            f"Concept '{concept.id}' join references unknown from_table '{rj.from_table}'."
                        )
                    if not schema.has_table(rj.to_table):
                        raise KnowledgeValidationError(
                            f"Concept '{concept.id}' join references unknown to_table '{rj.to_table}'."
                        )

    return bundle


if __name__ == "__main__":
    schema = inspect_schema()
    bundle = load_knowledge_bundle(schema=schema)
    print(f"Loaded {len(bundle.concepts)} OKF concepts successfully.")
    for cid, c in bundle.concepts.items():
        print(f" - [{c.type}] {cid} ({c.title})")

