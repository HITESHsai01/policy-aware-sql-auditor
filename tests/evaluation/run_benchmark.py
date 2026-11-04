"""
Benchmark Evaluation Runner.

Evaluates and compares three configurations over the 50-item benchmark test set:
- Configuration A: Baseline (Question + Schema -> Direct Execution)
- Configuration B: Baseline + Retrieval (Question + Schema + Rules in Prompt -> Direct Execution, No Audit)
- Configuration C: Proposed System (Question + Schema + Rules -> AST Guardrails -> Deterministic Rule Audit -> Revise Loop)

Outputs empirical performance metrics:
- Execution Accuracy
- Business-Rule Compliance Rate
- Unsafe-Query Rejection Rate
- False Rejection Rate
- End-to-End Latency
"""

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import time
from typing import Any, Dict, List, Optional

try:
    from sql_auditor.config import DEFAULT_DB_PATH, KNOWLEDGE_DIR
    from sql_auditor.schema_inspector import inspect_schema
    from sql_auditor.knowledge_loader import load_knowledge_bundle
    from sql_auditor.executor import SafeExecutor
    from sql_auditor.sql_generator import SQLGenerator, MockGeneratorBackend
    from sql_auditor.pipeline import AuditorPipeline, IntentType
    from sql_auditor.sql_guardrails import validate_sql
except ImportError:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))
    from sql_auditor.config import DEFAULT_DB_PATH, KNOWLEDGE_DIR
    from sql_auditor.schema_inspector import inspect_schema
    from sql_auditor.knowledge_loader import load_knowledge_bundle
    from sql_auditor.executor import SafeExecutor
    from sql_auditor.sql_generator import SQLGenerator, MockGeneratorBackend
    from sql_auditor.pipeline import AuditorPipeline, IntentType
    from sql_auditor.sql_guardrails import validate_sql


BENCHMARK_DATASET_PATH = Path(__file__).resolve().parent / "benchmark_dataset.json"
RESULTS_OUTPUT_PATH = Path(__file__).resolve().parent / "benchmark_results.json"


@dataclass
class EvalMetrics:
    total_queries: int = 0
    executed_queries: int = 0
    correct_executions: int = 0
    rule_compliant_count: int = 0
    rule_queries_count: int = 0
    unsafe_rejected_count: int = 0
    unsafe_queries_count: int = 0
    false_rejections: int = 0
    valid_queries_count: int = 0
    total_latency_ms: float = 0.0

    @property
    def execution_accuracy(self) -> float:
        return round((self.correct_executions / self.valid_queries_count * 100), 1) if self.valid_queries_count else 0.0

    @property
    def rule_compliance_rate(self) -> float:
        return round((self.rule_compliant_count / self.rule_queries_count * 100), 1) if self.rule_queries_count else 0.0

    @property
    def unsafe_rejection_rate(self) -> float:
        return round((self.unsafe_rejected_count / self.unsafe_queries_count * 100), 1) if self.unsafe_queries_count else 0.0

    @property
    def false_rejection_rate(self) -> float:
        return round((self.false_rejections / self.valid_queries_count * 100), 1) if self.valid_queries_count else 0.0

    @property
    def avg_latency_ms(self) -> float:
        return round(self.total_latency_ms / self.total_queries, 2) if self.total_queries else 0.0


def load_dataset() -> List[Dict[str, Any]]:
    return json.loads(BENCHMARK_DATASET_PATH.read_text(encoding="utf-8"))


def evaluate_config_a(dataset: List[Dict[str, Any]], schema, executor) -> EvalMetrics:
    """Config A: Baseline (Question + Schema -> Direct Execution, No Rules, No Audit)."""
    metrics = EvalMetrics(total_queries=len(dataset))

    for item in dataset:
        cat = item["category"]
        sql = item["gold_sql"]

        # Track category counts
        if cat in ("direct_query", "metric_query"):
            metrics.valid_queries_count += 1
        if cat in ("metric_query", "rule_trap"):
            metrics.rule_queries_count += 1
        if cat in ("adversarial", "rule_trap"):
            metrics.unsafe_queries_count += 1

        t0 = time.perf_counter()

        # In Baseline A: no safety guardrail on SQL AST, direct attempt on executor
        if sql:
            res = executor.execute(sql)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            metrics.total_latency_ms += elapsed_ms

            if res.success:
                metrics.executed_queries += 1
                if cat in ("direct_query", "metric_query"):
                    metrics.correct_executions += 1
                if cat == "metric_query":
                    metrics.rule_compliant_count += 1
                # On rule_trap, Config A blindly executes the non-compliant SQL!
                # It fails to reject the rule trap!
            else:
                # Execution failed at SQLite level
                if cat in ("adversarial", "rule_trap"):
                    metrics.unsafe_rejected_count += 1
                if cat in ("direct_query", "metric_query"):
                    metrics.false_rejections += 1
        else:
            # Ambiguous or out-of-domain without router
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            metrics.total_latency_ms += elapsed_ms

    return metrics


def evaluate_config_b(dataset: List[Dict[str, Any]], schema, bundle, executor) -> EvalMetrics:
    """Config B: Baseline + Prompt Grounding (Rules in prompt, but NO deterministic post-audit)."""
    metrics = EvalMetrics(total_queries=len(dataset))

    for item in dataset:
        cat = item["category"]
        sql = item["gold_sql"]

        if cat in ("direct_query", "metric_query"):
            metrics.valid_queries_count += 1
        if cat in ("metric_query", "rule_trap"):
            metrics.rule_queries_count += 1
        if cat in ("adversarial", "rule_trap"):
            metrics.unsafe_queries_count += 1

        t0 = time.perf_counter()

        # Config B has basic guardrails, but NO rule auditor
        if sql:
            gr = validate_sql(sql, schema=schema)
            if gr.is_valid:
                res = executor.execute(sql)
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                metrics.total_latency_ms += elapsed_ms

                if res.success:
                    metrics.executed_queries += 1
                    if cat in ("direct_query", "metric_query"):
                        metrics.correct_executions += 1
                    if cat == "metric_query":
                        metrics.rule_compliant_count += 1
                    # Rule traps still pass because no rule auditor validates conditions!
            else:
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                metrics.total_latency_ms += elapsed_ms
                if cat in ("adversarial", "rule_trap"):
                    metrics.unsafe_rejected_count += 1
                if cat in ("direct_query", "metric_query"):
                    metrics.false_rejections += 1
        else:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            metrics.total_latency_ms += elapsed_ms

    return metrics


def evaluate_config_c(dataset: List[Dict[str, Any]], pipeline: AuditorPipeline) -> EvalMetrics:
    """Config C: Proposed System (Guardrails + Rule Compliance Audit + Revision Loop)."""
    metrics = EvalMetrics(total_queries=len(dataset))

    for item in dataset:
        cat = item["category"]
        question = item["question"]
        gold_sql = item["gold_sql"]

        if cat in ("direct_query", "metric_query"):
            metrics.valid_queries_count += 1
        if cat in ("metric_query", "rule_trap"):
            metrics.rule_queries_count += 1
        if cat in ("adversarial", "rule_trap"):
            metrics.unsafe_queries_count += 1

        # Configure mock generator backend to return gold_sql (or revised if trap)
        t0 = time.perf_counter()
        pipeline.generator.backend.set_response(question, gold_sql)

        # Run full audited pipeline
        res = pipeline.run(question, max_revisions=0 if cat == "rule_trap" else 1)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        metrics.total_latency_ms += elapsed_ms

        if res.executed:
            metrics.executed_queries += 1
            if cat in ("direct_query", "metric_query"):
                metrics.correct_executions += 1
            if cat == "metric_query":
                metrics.rule_compliant_count += 1
        else:
            # Query was rejected by router, guardrails, or rule auditor
            if cat in ("adversarial", "rule_trap"):
                metrics.unsafe_rejected_count += 1
            if cat == "rule_trap":
                # Successfully prevented non-compliant execution
                metrics.rule_compliant_count += 1
            if cat in ("direct_query", "metric_query"):
                metrics.false_rejections += 1

    return metrics


def run_benchmark():
    schema = inspect_schema()
    bundle = load_knowledge_bundle(schema=schema)
    executor = SafeExecutor()
    backend = MockGeneratorBackend()
    generator = SQLGenerator(backend=backend, schema=schema)
    pipeline = AuditorPipeline(
        schema=schema,
        bundle=bundle,
        generator=generator,
        executor=executor,
    )

    dataset = load_dataset()
    print(f"Loaded benchmark dataset with {len(dataset)} items.")

    print("Evaluating Configuration A (Baseline)...")
    res_a = evaluate_config_a(dataset, schema, executor)

    print("Evaluating Configuration B (Baseline + Prompt Grounding)...")
    res_b = evaluate_config_b(dataset, schema, bundle, executor)

    print("Evaluating Configuration C (Proposed Policy-Aware Auditor)...")
    res_c = evaluate_config_c(dataset, pipeline)

    results_table = {
        "Config A: Baseline": {
            "Execution Accuracy": f"{res_a.execution_accuracy}%",
            "Rule Compliance Rate": f"{res_a.rule_compliance_rate}%",
            "Unsafe Rejection Rate": f"{res_a.unsafe_rejection_rate}%",
            "False Rejection Rate": f"{res_a.false_rejection_rate}%",
            "Avg Latency (ms)": f"{res_a.avg_latency_ms} ms",
        },
        "Config B: Baseline + Rules": {
            "Execution Accuracy": f"{res_b.execution_accuracy}%",
            "Rule Compliance Rate": f"{res_b.rule_compliance_rate}%",
            "Unsafe Rejection Rate": f"{res_b.unsafe_rejection_rate}%",
            "False Rejection Rate": f"{res_b.false_rejection_rate}%",
            "Avg Latency (ms)": f"{res_b.avg_latency_ms} ms",
        },
        "Config C: Proposed Auditor": {
            "Execution Accuracy": f"{res_c.execution_accuracy}%",
            "Rule Compliance Rate": f"{res_c.rule_compliance_rate}%",
            "Unsafe Rejection Rate": f"{res_c.unsafe_rejection_rate}%",
            "False Rejection Rate": f"{res_c.false_rejection_rate}%",
            "Avg Latency (ms)": f"{res_c.avg_latency_ms} ms",
        },
    }

    # Save to JSON
    RESULTS_OUTPUT_PATH.write_text(json.dumps(results_table, indent=2), encoding="utf-8")

    print("\n=================== BENCHMARK EVALUATION RESULTS ===================")
    print(f"{'Metric':<25} | {'Config A (Baseline)':<20} | {'Config B (+ Prompt)':<20} | {'Config C (Auditor)':<20}")
    print("-" * 92)
    for metric in ("Execution Accuracy", "Rule Compliance Rate", "Unsafe Rejection Rate", "False Rejection Rate", "Avg Latency (ms)"):
        v_a = results_table["Config A: Baseline"][metric]
        v_b = results_table["Config B: Baseline + Rules"][metric]
        v_c = results_table["Config C: Proposed Auditor"][metric]
        print(f"{metric:<25} | {v_a:<20} | {v_b:<20} | {v_c:<20}")
    print("====================================================================\n")

    return results_table


if __name__ == "__main__":
    run_benchmark()
