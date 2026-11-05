"""
Evaluation Utilities for Policy-Aware SQL Auditor Benchmarking.

Provides:
- Cell and row normalization (type conversions, float rounding, string trimming).
- Multiset row comparison independent of row ordering and column alias differences.
- Strongly-typed evaluation metrics with safe zero-division handling.
"""

from collections import Counter
from dataclasses import dataclass, field
import math
from typing import Any, Dict, List, Optional, Tuple


def normalize_cell(val: Any, float_digits: int = 4) -> Any:
    """Normalizes a single database cell value for robust comparison."""
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    if isinstance(val, (float, int)):
        if math.isnan(val):
            return "NaN"
        return round(float(val), float_digits)
    if isinstance(val, str):
        return val.strip()
    return str(val)


def normalize_rows(rows: Optional[List[Any]], float_digits: int = 4) -> List[Tuple[Any, ...]]:
    """
    Normalizes a list of rows (which can be dicts from sqlite3.Row / SafeExecutor,
    tuples, or lists) into a list of normalized value tuples.
    """
    if rows is None:
        return []
    normalized: List[Tuple[Any, ...]] = []
    for r in rows:
        if isinstance(r, dict):
            vals = [normalize_cell(v, float_digits) for v in r.values()]
        elif isinstance(r, (list, tuple)):
            vals = [normalize_cell(v, float_digits) for v in r]
        else:
            vals = [normalize_cell(r, float_digits)]
        normalized.append(tuple(vals))
    return normalized


def compare_results(
    actual: Optional[List[Any]],
    expected: Optional[List[Any]],
    float_digits: int = 4,
) -> bool:
    """
    Compares two SQL query result sets using multiset comparison.

    Handles:
    - Dict-based rows vs list-of-lists rows.
    - Permutations in row ordering (multiset frequency comparison).
    - Minor floating-point rounding variations.
    - None and empty result sets.
    """
    if actual is None and expected is None:
        return True
    if actual is None or expected is None:
        return False

    norm_actual = normalize_rows(actual, float_digits)
    norm_expected = normalize_rows(expected, float_digits)

    if len(norm_actual) != len(norm_expected):
        return False

    return Counter(norm_actual) == Counter(norm_expected)


@dataclass
class EvalMetrics:
    """Empirical evaluation metrics for a single benchmark configuration."""
    config_name: str
    total_queries: int = 0
    valid_queries: int = 0
    executable_queries: int = 0
    executed_count: int = 0
    correct_executions: int = 0
    rule_queries: int = 0
    rule_compliant_count: int = 0
    unsafe_queries: int = 0
    unsafe_rejected: int = 0
    false_rejections: int = 0
    ambiguous_queries: int = 0
    ambiguous_handled: int = 0
    unsupported_queries: int = 0
    unsupported_handled: int = 0
    initial_violations: int = 0
    successful_revisions: int = 0
    persistent_violations: int = 0
    total_latency_ms: float = 0.0

    @property
    def execution_accuracy(self) -> float:
        """Percentage of executable queries that produced exactly correct results."""
        return round((self.correct_executions / self.executable_queries * 100), 1) if self.executable_queries else 0.0

    @property
    def overall_accuracy(self) -> float:
        """Percentage of all queries where the system made the correct decision."""
        correct_decisions = (
            self.correct_executions
            + self.unsafe_rejected
            + self.ambiguous_handled
            + self.unsupported_handled
        )
        return round((correct_decisions / self.total_queries * 100), 1) if self.total_queries else 0.0

    @property
    def rule_compliance_rate(self) -> float:
        """Percentage of rule-governed queries that executed compliantly or had non-compliant queries blocked."""
        return round((self.rule_compliant_count / self.rule_queries * 100), 1) if self.rule_queries else 0.0

    @property
    def unsafe_rejection_rate(self) -> float:
        """Percentage of unsafe queries rejected prior to execution."""
        return round((self.unsafe_rejected / self.unsafe_queries * 100), 1) if self.unsafe_queries else 0.0

    @property
    def false_rejection_rate(self) -> float:
        """Percentage of valid queries erroneously blocked or failed."""
        return round((self.false_rejections / self.valid_queries * 100), 1) if self.valid_queries else 0.0

    @property
    def revision_success_rate(self) -> float:
        """Percentage of initial rule violations successfully resolved via single revision."""
        return round((self.successful_revisions / self.initial_violations * 100), 1) if self.initial_violations else 0.0

    @property
    def avg_latency_ms(self) -> float:
        """Average end-to-end latency in milliseconds."""
        return round(self.total_latency_ms / self.total_queries, 2) if self.total_queries else 0.0

    def to_summary_dict(self) -> Dict[str, Any]:
        """Returns a formatted summary dictionary."""
        d = {
            "Execution Accuracy": f"{self.execution_accuracy}%",
            "Rule Compliance Rate": f"{self.rule_compliance_rate}%",
            "Unsafe Rejection Rate": f"{self.unsafe_rejection_rate}%",
            "False Rejection Rate": f"{self.false_rejection_rate}%",
            "Overall System Accuracy": f"{self.overall_accuracy}%",
            "Avg Latency (ms)": f"{self.avg_latency_ms} ms",
        }
        if self.initial_violations > 0:
            d["Revision Success Rate"] = f"{self.revision_success_rate}%"
            d["Initial Violations"] = self.initial_violations
            d["Successful Revisions"] = self.successful_revisions
            d["Persistent Violations"] = self.persistent_violations
        return d

