"""
Deterministic Rule-Compliance Auditor Module.

Performs static semantic AST auditing over candidate SQL against versioned
business rules (OKF concepts). Verifies that required predicates, date boundaries,
and join relationships are satisfied, while strictly rejecting forbidden substitute columns.
"""

from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Any, Dict, List, Optional, Set, Tuple
import sqlglot
from sqlglot import exp

try:
    from sql_auditor.knowledge_loader import ConceptDefinition, RequiredFilter, RequiredJoin, ForbiddenSubstitute
    from sql_auditor.schema_inspector import DatabaseSchema
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from sql_auditor.knowledge_loader import ConceptDefinition, RequiredFilter, RequiredJoin, ForbiddenSubstitute
    from sql_auditor.schema_inspector import DatabaseSchema


class AuditStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


@dataclass
class RuleViolation:
    rule_id: str
    rule_version: int
    violation_type: str  # MISSING_FILTER, FORBIDDEN_SUBSTITUTE, MISSING_JOIN, MISSING_DATE_BOUNDS
    message: str


@dataclass
class RuleAuditResult:
    status: AuditStatus
    rule_ids: List[str] = field(default_factory=list)
    violations: List[RuleViolation] = field(default_factory=list)
    passed_rules: List[str] = field(default_factory=list)

    @property
    def is_compliant(self) -> bool:
        return self.status == AuditStatus.PASS and len(self.violations) == 0

    def summary_message(self) -> str:
        if self.is_compliant:
            return f"Query compliant with {len(self.passed_rules)} evaluated business rule(s)."
        messages = [f"[{v.rule_id}] {v.message}" for v in self.violations]
        return "Rule audit failed:\n" + "\n".join(messages)


class RuleAuditor:
    """Deterministic semantic rule auditor for candidate SQL queries."""

    def __init__(self, schema: Optional[DatabaseSchema] = None):
        self.schema = schema

    def audit(
        self,
        sql: str,
        rules: List[ConceptDefinition],
        context: Optional[Dict[str, Any]] = None,
        dialect: str = "sqlite",
    ) -> RuleAuditResult:
        """
        Audits a SQL query against a list of retrieved business concepts.

        Args:
            sql: The candidate SQL query to audit.
            rules: The list of OKF ConceptDefinition objects retrieved for this query.
            context: Optional context containing parameters like fiscal_year or target_date.
            dialect: SQLGlot dialect.

        Returns:
            RuleAuditResult with PASS/FAIL status and detailed violation diagnostics.
        """
        context = context or {}
        # Parse query with SQLGlot
        try:
            ast = sqlglot.parse_one(sql.strip(), read=dialect)
        except Exception as e:
            return RuleAuditResult(
                status=AuditStatus.FAIL,
                violations=[
                    RuleViolation(
                        rule_id="syntax_check",
                        rule_version=1,
                        violation_type="PARSE_ERROR",
                        message=f"Query failed AST parsing during rule audit: {str(e)}",
                    )
                ],
            )

        # 1. Build Table Alias Map
        alias_map = self._build_alias_map(ast)

        # 2. Extract and Normalize Conditions from WHERE and JOIN ON clauses
        conditions = self._extract_conditions(ast, alias_map)

        # 3. Extract all referenced columns (table.column)
        referenced_columns = self._extract_referenced_columns(ast, alias_map)

        # 4. Check each rule
        violations: List[RuleViolation] = []
        passed_rules: List[str] = []
        evaluated_rule_ids: List[str] = []

        for concept in rules:
            if concept.type in ("index", "table"):
                continue

            # Policies only apply if at least one of their governed tables is present in the query
            tables_in_query = set(alias_map.values())
            if concept.type == "policy":
                if not any(t.lower() in tables_in_query for t in concept.tables):
                    continue

            rule_tag = f"{concept.id}@v{concept.version}"
            evaluated_rule_ids.append(rule_tag)
            concept_violations: List[RuleViolation] = []

            # Check forbidden substitutes
            for fs in concept.forbidden_substitutes:
                canonical_forbidden = self._canonical_col_name(fs.column)
                if canonical_forbidden in referenced_columns:
                    concept_violations.append(
                        RuleViolation(
                            rule_id=concept.id,
                            rule_version=concept.version,
                            violation_type="FORBIDDEN_SUBSTITUTE",
                            message=f"Forbidden substitute column used: {canonical_forbidden}. {fs.reason}",
                        )
                    )

            # Check required filters
            for rf in concept.required_filters:
                v = self._check_required_filter(rf, conditions, context, concept)
                if v:
                    concept_violations.append(v)

            # Check required joins
            for rj in concept.required_joins:
                v = self._check_required_join(rj, ast, alias_map, concept)
                if v:
                    concept_violations.append(v)

            if concept_violations:
                violations.extend(concept_violations)
            else:
                passed_rules.append(rule_tag)

        status = AuditStatus.PASS if not violations else AuditStatus.FAIL
        return RuleAuditResult(
            status=status,
            rule_ids=evaluated_rule_ids,
            violations=violations,
            passed_rules=passed_rules,
        )

    def _build_alias_map(self, ast: exp.Expression) -> Dict[str, str]:
        """Maps aliases and table names to lowercased canonical table names."""
        alias_map: Dict[str, str] = {}
        for tbl in ast.find_all(exp.Table):
            t_name = tbl.name.lower()
            alias = tbl.alias.lower() if tbl.alias else t_name
            alias_map[alias] = t_name
            alias_map[t_name] = t_name
        return alias_map

    def _canonical_col_name(self, col_str: str) -> str:
        """Returns table.column in lowercase."""
        return col_str.strip().lower()

    def _extract_referenced_columns(self, ast: exp.Expression, alias_map: Dict[str, str]) -> Set[str]:
        """Extracts all canonical table.column identifiers referenced in the query."""
        cols: Set[str] = set()
        for c in ast.find_all(exp.Column):
            c_name = c.name.lower()
            if c_name == "*":
                continue
            t_alias = c.table.lower() if c.table else None
            if t_alias:
                resolved_table = alias_map.get(t_alias, t_alias)
                cols.add(f"{resolved_table}.{c_name}")
            elif self.schema:
                # Unqualified column: locate owning table from schema
                for tbl_name in set(alias_map.values()):
                    if self.schema.has_column(tbl_name, c_name):
                        cols.add(f"{tbl_name}.{c_name}")
                        break
            else:
                cols.add(c_name)
        return cols

    def _extract_conditions(self, ast: exp.Expression, alias_map: Dict[str, str]) -> List[Dict[str, Any]]:
        """
        Extracts and normalizes conditions from WHERE and JOIN ON expressions.
        Handles EQ, In, Between, GTE/LTE, and date functions (strftime).
        """
        conditions: List[Dict[str, Any]] = []

        # Find all nodes in WHERE and JOIN ON clauses
        condition_roots = []
        for where_node in ast.find_all(exp.Where):
            condition_roots.append(where_node)
        for join_node in ast.find_all(exp.Join):
            if join_node.args.get("on"):
                condition_roots.append(join_node.args["on"])

        for root in condition_roots:
            for node in root.walk():
                # 1. Equality: col = 'value'
                if isinstance(node, exp.EQ):
                    cond = self._parse_eq(node, alias_map)
                    if cond:
                        conditions.append(cond)

                # 2. IN clause: col IN ('value')
                elif isinstance(node, exp.In):
                    cond = self._parse_in(node, alias_map)
                    if cond:
                        conditions.append(cond)

                # 3. Between clause: col BETWEEN 'start' AND 'end'
                elif isinstance(node, exp.Between):
                    cond = self._parse_between(node, alias_map)
                    if cond:
                        conditions.append(cond)

                # 4. Binary comparisons: col >= 'val' or col <= 'val'
                elif isinstance(node, (exp.GTE, exp.GT, exp.LTE, exp.LT)):
                    cond = self._parse_comparison(node, alias_map)
                    if cond:
                        conditions.append(cond)

        return conditions

    def _resolve_col_string(self, col_node: exp.Column, alias_map: Dict[str, str]) -> str:
        c_name = col_node.name.lower()
        t_alias = col_node.table.lower() if col_node.table else None
        if t_alias:
            resolved_table = alias_map.get(t_alias, t_alias)
            return f"{resolved_table}.{c_name}"
        if self.schema:
            for tbl_name in set(alias_map.values()):
                if self.schema.has_column(tbl_name, c_name):
                    return f"{tbl_name}.{c_name}"
        return c_name

    def _parse_eq(self, node: exp.EQ, alias_map: Dict[str, str]) -> Optional[Dict[str, Any]]:
        left = node.this
        right = node.expression

        # Standard: Column = Literal
        if isinstance(left, exp.Column) and isinstance(right, exp.Literal):
            col_str = self._resolve_col_string(left, alias_map)
            val_str = str(right.this).strip("'\"").lower()
            return {"type": "EQ", "column": col_str, "value": val_str}

        # Symmetric: Literal = Column
        if isinstance(right, exp.Column) and isinstance(left, exp.Literal):
            col_str = self._resolve_col_string(right, alias_map)
            val_str = str(left.this).strip("'\"").lower()
            return {"type": "EQ", "column": col_str, "value": val_str}

        # Date function: strftime('%Y', col) = '2024' (parsed as TimeToStr or Anonymous)
        col_found = None
        for inner in left.walk():
            if isinstance(inner, exp.Column):
                col_found = self._resolve_col_string(inner, alias_map)
                break
        if col_found and isinstance(right, exp.Literal):
            val_str = str(right.this).strip("'\"").lower()
            return {"type": "DATE_FUNC_EQ", "column": col_found, "value": val_str, "raw_func": str(left)}

        return None

    def _parse_in(self, node: exp.In, alias_map: Dict[str, str]) -> Optional[Dict[str, Any]]:
        if not isinstance(node.this, exp.Column):
            return None
        col_str = self._resolve_col_string(node.this, alias_map)
        values = []
        for expr in node.expressions:
            if isinstance(expr, exp.Literal):
                values.append(str(expr.this).strip("'\"").lower())
        return {"type": "IN", "column": col_str, "values": values}

    def _parse_between(self, node: exp.Between, alias_map: Dict[str, str]) -> Optional[Dict[str, Any]]:
        if not isinstance(node.this, exp.Column):
            return None
        col_str = self._resolve_col_string(node.this, alias_map)
        low_val = str(node.args.get("low", "")).strip("'\"")
        high_val = str(node.args.get("high", "")).strip("'\"")
        return {"type": "BETWEEN", "column": col_str, "low": low_val, "high": high_val}

    def _parse_comparison(self, node: exp.Expression, alias_map: Dict[str, str]) -> Optional[Dict[str, Any]]:
        left = node.this
        right = getattr(node, "expression", None)
        if isinstance(left, exp.Column) and isinstance(right, exp.Literal):
            col_str = self._resolve_col_string(left, alias_map)
            val_str = str(right.this).strip("'\"")
            op_name = type(node).__name__
            return {"type": op_name, "column": col_str, "value": val_str}
        return None

    def _check_required_filter(
        self,
        rf: RequiredFilter,
        conditions: List[Dict[str, Any]],
        context: Dict[str, Any],
        concept: ConceptDefinition,
    ) -> Optional[RuleViolation]:
        canonical_target_col = self._canonical_col_name(rf.column)

        # 1. Exact value equality or single IN equivalence
        if rf.operator == "=" and rf.value is not None:
            expected_val = str(rf.value).lower()
            found = False
            for cond in conditions:
                cond_col = self._canonical_col_name(cond.get("column", ""))
                # Compare column: either exact table.col or col name
                if cond_col == canonical_target_col or cond_col.endswith(f".{canonical_target_col.split('.')[-1]}"):
                    if cond["type"] == "EQ" and cond.get("value") == expected_val:
                        found = True
                        break
                    if cond["type"] == "IN" and expected_val in cond.get("values", []):
                        found = True
                        break

            if not found:
                return RuleViolation(
                    rule_id=concept.id,
                    rule_version=concept.version,
                    violation_type="MISSING_FILTER",
                    message=f"Missing required filter: {canonical_target_col} = '{rf.value}'.",
                )

        # 2. Fiscal Year Range
        elif rf.type == "fiscal_year_range":
            target_year = context.get("fiscal_year") or context.get("year")
            # If target year known, check year match; otherwise check that any valid fiscal year boundary exists
            has_date_filter = False
            for cond in conditions:
                cond_col = self._canonical_col_name(cond.get("column", ""))
                if cond_col == canonical_target_col or cond_col.endswith(".expense_date"):
                    if cond["type"] == "BETWEEN":
                        if target_year:
                            y_str = str(target_year)
                            if y_str in str(cond.get("low")) and y_str in str(cond.get("high")):
                                has_date_filter = True
                                break
                        else:
                            has_date_filter = True
                            break
                    elif cond["type"] == "DATE_FUNC_EQ":
                        if target_year:
                            if cond.get("value") == str(target_year):
                                has_date_filter = True
                                break
                        else:
                            has_date_filter = True
                            break
                    elif cond["type"] in ("GTE", "GT", "LTE", "LT"):
                        has_date_filter = True
                        break

            if not has_date_filter:
                year_info = f" for fiscal year {target_year}" if target_year else ""
                return RuleViolation(
                    rule_id=concept.id,
                    rule_version=concept.version,
                    violation_type="MISSING_DATE_BOUNDS",
                    message=f"Missing required fiscal year date boundary filter on {canonical_target_col}{year_info}.",
                )

        # 3. Relative date range (e.g. trailing 90 days for active customer)
        elif rf.type == "relative_date_range":
            has_window_filter = False
            for cond in conditions:
                cond_col = self._canonical_col_name(cond.get("column", ""))
                if cond_col == canonical_target_col or cond_col.endswith(".order_date"):
                    if cond["type"] in ("BETWEEN", "GTE", "GT"):
                        has_window_filter = True
                        break
                    if cond["type"] == "DATE_FUNC_EQ":
                        has_window_filter = True
                        break

            if not has_window_filter:
                return RuleViolation(
                    rule_id=concept.id,
                    rule_version=concept.version,
                    violation_type="MISSING_DATE_BOUNDS",
                    message=f"Missing required trailing date filter on {canonical_target_col} (expected {rf.window_days or 90}-day activity window).",
                )

        return None

    def _check_required_join(
        self,
        rj: RequiredJoin,
        ast: exp.Expression,
        alias_map: Dict[str, str],
        concept: ConceptDefinition,
    ) -> Optional[RuleViolation]:
        tables_in_query = set(alias_map.values())
        req_from = rj.from_table.lower()
        req_to = rj.to_table.lower()

        # If both tables are present in the query, verify they are properly joined
        if req_from in tables_in_query and req_to in tables_in_query:
            has_join_condition = False
            for join_node in ast.find_all(exp.Join):
                if join_node.args.get("on"):
                    on_sql = str(join_node.args["on"]).lower()
                    if any(
                        alias in on_sql for alias, t in alias_map.items() if t in (req_from, req_to)
                    ):
                        has_join_condition = True
                        break

            if not has_join_condition:
                for where_node in ast.find_all(exp.Where):
                    w_sql = str(where_node).lower()
                    has_from = any(a in w_sql for a, t in alias_map.items() if t == req_from)
                    has_to = any(a in w_sql for a, t in alias_map.items() if t == req_to)
                    if has_from and has_to:
                        has_join_condition = True
                        break

            if not has_join_condition:
                return RuleViolation(
                    rule_id=concept.id,
                    rule_version=concept.version,
                    violation_type="MISSING_JOIN",
                    message=f"Missing required join condition between '{req_from}' and '{req_to}'. Relationship defined as: {rj.on}",
                )

        return None

