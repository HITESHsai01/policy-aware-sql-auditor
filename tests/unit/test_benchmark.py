"""
Unit Tests for Benchmark Dataset, Evaluation Utilities, and Configurations.

Ensures:
- Benchmark dataset structural integrity, uniqueness of IDs, and validity of fixtures.
- Multiset result comparison accuracy with column and row permutation insensitivity.
- Safe zero-division handling across all metric formulas.
- Independence of candidate SQL generation from ground truth gold SQL.
- Correct execution of the evaluation harness.
"""

from collections import Counter
import json
from pathlib import Path
import pytest

from sql_auditor.schema_inspector import inspect_schema
from sql_auditor.knowledge_loader import load_knowledge_bundle
from tests.evaluation.eval_utils import compare_results, normalize_cell, normalize_rows, EvalMetrics
from tests.evaluation.run_benchmark import (
    DEFAULT_DATASET_PATH,
    DEFAULT_CANDIDATES_PATH,
    run_benchmark,
)


class TestBenchmarkDatasetIntegrity:
    """Validates the frozen benchmark test suite."""

    @pytest.fixture(autouse=True)
    def setup_data(self):
        assert DEFAULT_DATASET_PATH.exists(), f"Missing dataset: {DEFAULT_DATASET_PATH}"
        self.dataset = json.loads(DEFAULT_DATASET_PATH.read_text(encoding="utf-8"))
        self.schema = inspect_schema()
        self.bundle = load_knowledge_bundle(schema=self.schema)

    def test_dataset_size_and_categories(self):
        """Ensures exactly 50 items with the expected category distribution."""
        assert len(self.dataset) == 50
        counts = Counter(item["category"] for item in self.dataset)
        assert counts["direct_query"] == 10
        assert counts["metric_query"] == 10
        assert counts["rule_trap"] == 10
        assert counts["adversarial"] == 10
        assert counts["ambiguous"] == 5
        assert counts["out_of_domain"] == 5

    def test_unique_ids(self):
        """Ensures all question IDs are unique."""
        ids = [item["id"] for item in self.dataset]
        assert len(ids) == len(set(ids))

    def test_required_fields_present(self):
        """Ensures all mandatory fields exist across all items."""
        required_keys = {"id", "category", "question", "expected_safety", "expected_behavior"}
        for item in self.dataset:
            missing = required_keys - set(item.keys())
            assert not missing, f"Item {item.get('id')} missing keys: {missing}"

    def test_valid_expected_results_for_executable_queries(self):
        """Valid queries must have valid non-empty expected results and gold SQL."""
        for item in self.dataset:
            cat = item["category"]
            qid = item["id"]
            if cat in ("direct_query", "metric_query", "rule_trap"):
                assert item.get("gold_sql") is not None, f"Query {qid} missing gold_sql"
                assert item.get("expected_result") is not None, f"Query {qid} missing expected_result"
                assert len(item["expected_result"]) > 0, f"Query {qid} has empty expected_result"
            else:
                assert item.get("gold_sql") is None, f"Adversarial/ambiguous query {qid} should not have gold_sql"
                assert item.get("expected_result") is None, f"Query {qid} should have null expected_result"

    def test_rule_references_valid(self):
        """All applicable rule IDs in dataset must resolve against the KnowledgeBundle."""
        for item in self.dataset:
            for rule_id in item.get("applicable_rules", []):
                concept = self.bundle.get(rule_id)
                assert concept is not None, f"Item {item['id']} references unknown rule: {rule_id}"


class TestResultComparison:
    """Tests the multiset row and cell comparison utility."""

    def test_exact_matches(self):
        actual = [{"id": 1, "name": "Engineering"}, {"id": 2, "name": "Marketing"}]
        expected = [[1, "Engineering"], [2, "Marketing"]]
        assert compare_results(actual, expected) is True

    def test_row_order_insensitivity(self):
        actual = [[2, "Marketing"], [1, "Engineering"]]
        expected = [[1, "Engineering"], [2, "Marketing"]]
        assert compare_results(actual, expected) is True

    def test_float_precision_tolerance(self):
        actual = [[113285.71428571429]]
        expected = [[113285.7143]]
        assert compare_results(actual, expected) is True

    def test_mismatched_results(self):
        actual = [[575000.0]]
        expected = [[450000.0]]
        assert compare_results(actual, expected) is False

    def test_empty_and_none_results(self):
        assert compare_results(None, None) is True
        assert compare_results([], []) is True
        assert compare_results([[1]], None) is False
        assert compare_results([], [[1]]) is False

    def test_cell_normalization(self):
        assert normalize_cell("  Engineering  ") == "Engineering"
        assert normalize_cell(450000.00001) == 450000.0
        assert normalize_cell(None) is None
        assert normalize_cell(True) is True


class TestEvalMetricsZeroDivision:
    """Verifies that all metric calculations handle zero denominators safely without exceptions."""

    def test_zero_denominator_safety(self):
        m = EvalMetrics(config_name="Empty Config")
        assert m.execution_accuracy == 0.0
        assert m.overall_accuracy == 0.0
        assert m.rule_compliance_rate == 0.0
        assert m.unsafe_rejection_rate == 0.0
        assert m.false_rejection_rate == 0.0
        assert m.revision_success_rate == 0.0
        assert m.avg_latency_ms == 0.0

        summary = m.to_summary_dict()
        assert summary["Execution Accuracy"] == "0.0%"
        assert "Revision Success Rate" not in summary

    def test_populated_metrics_calculation(self):
        m = EvalMetrics(
            config_name="Test Config",
            total_queries=50,
            executable_queries=30,
            correct_executions=29,
            rule_queries=21,
            rule_compliant_count=21,
            unsafe_queries=10,
            unsafe_rejected=10,
            valid_queries=20,
            false_rejections=0,
            initial_violations=10,
            successful_revisions=9,
            persistent_violations=1,
            total_latency_ms=100.0,
        )
        assert m.execution_accuracy == 96.7
        assert m.rule_compliance_rate == 100.0
        assert m.unsafe_rejection_rate == 100.0
        assert m.false_rejection_rate == 0.0
        assert m.revision_success_rate == 90.0
        assert m.avg_latency_ms == 2.0


class TestMockCandidatesIndependence:
    """Ensures candidate SQL for evaluation is stored separately and independent of gold SQL."""

    def test_mock_candidates_file_exists(self):
        assert DEFAULT_CANDIDATES_PATH.exists()
        candidates = json.loads(DEFAULT_CANDIDATES_PATH.read_text(encoding="utf-8"))
        assert "config_a" in candidates
        assert "config_b" in candidates
        assert "config_c_initial" in candidates
        assert "config_c_revised" in candidates

    def test_candidates_differ_from_gold_where_appropriate(self):
        dataset = json.loads(DEFAULT_DATASET_PATH.read_text(encoding="utf-8"))
        candidates = json.loads(DEFAULT_CANDIDATES_PATH.read_text(encoding="utf-8"))

        dataset_map = {item["id"]: item for item in dataset}

        # Rule traps in config_a and config_b must NOT be the compliant gold SQL!
        for qid in ("bench_21", "bench_22", "bench_24", "bench_25"):
            gold_sql = dataset_map[qid]["gold_sql"].strip()
            cand_a = candidates["config_a"][qid].strip()
            cand_b = candidates["config_b"][qid].strip()
            assert cand_a != gold_sql, f"{qid} in config_a improperly matches gold_sql"
            assert cand_b != gold_sql, f"{qid} in config_b improperly matches gold_sql"


class TestHarnessExecution:
    """Verifies that the benchmark runner executes end-to-end and writes valid results."""

    def test_run_benchmark_mock_mode(self, tmp_path):
        out_file = tmp_path / "test_results.json"
        results = run_benchmark(
            mode="mock",
            output_path=out_file,
        )
        assert out_file.exists()
        assert "summary" in results
        assert "Config A: Baseline" in results["summary"]
        assert "Config B: Baseline + Rules" in results["summary"]
        assert "Config C: Proposed Auditor" in results["summary"]
        assert "revision_effectiveness" in results

    def test_evaluate_config_a_and_b_with_generator(self):
        from tests.evaluation.run_benchmark import evaluate_config_a, evaluate_config_b
        from sql_auditor.schema_inspector import inspect_schema
        from sql_auditor.knowledge_loader import load_knowledge_bundle
        from sql_auditor.executor import SafeExecutor
        from sql_auditor.rule_auditor import RuleAuditor
        from sql_auditor.sql_generator import SQLGenerator, MockGeneratorBackend

        schema = inspect_schema()
        bundle = load_knowledge_bundle(schema=schema)
        executor = SafeExecutor()
        rule_auditor = RuleAuditor(schema=schema)
        backend = MockGeneratorBackend(default_response="SELECT 1;")
        generator = SQLGenerator(backend=backend, schema=schema)

        mini_dataset = [{
            "id": "test_01",
            "category": "direct_query",
            "question": "test query?",
            "expected_result": [[1]],
            "applicable_rules": [],
        }]

        metrics_a, itemized_a = evaluate_config_a(
            mini_dataset, candidates={}, schema=schema, bundle=bundle,
            executor=executor, rule_auditor=rule_auditor, generator=generator
        )
        assert itemized_a[0]["candidate_sql"] == "SELECT 1;"

        metrics_b, itemized_b = evaluate_config_b(
            mini_dataset, candidates={}, schema=schema, bundle=bundle,
            executor=executor, rule_auditor=rule_auditor, generator=generator
        )
        assert itemized_b[0]["candidate_sql"] == "SELECT 1;"


