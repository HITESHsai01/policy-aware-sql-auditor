"""
Benchmark Evaluation Runner for Policy-Aware SQL Auditor.

Evaluates and rigorously compares three configurations over the 50-item benchmark test set:
- Configuration A: Baseline (Question + Schema -> Direct Execution, No Rules in Prompt, No Rule Audit)
- Configuration B: Baseline + Prompt Grounding (Question + Schema + Rules in Prompt -> AST Guardrails -> Execution, No Semantic Rule Audit)
- Configuration C: Proposed Policy-Aware Auditor (Router -> Retrieval -> Generator -> AST Guardrails -> Semantic Rule Audit -> Revise Loop -> Safe Execution)

Methodology Integrity:
- Gold SQL is strictly ground truth for verification, NEVER supplied as candidate SQL to the system under test.
- Precomputed expected result fixtures generated from data/auditor.db provide independent verification.
- Supports both offline deterministic mock evaluation (default) and real LLM evaluation (Ollama).
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Tuple

try:
    from sql_auditor.config import DEFAULT_DB_PATH, KNOWLEDGE_DIR
    from sql_auditor.schema_inspector import inspect_schema, DatabaseSchema
    from sql_auditor.knowledge_loader import load_knowledge_bundle, KnowledgeBundle
    from sql_auditor.executor import SafeExecutor
    from sql_auditor.sql_generator import SQLGenerator, MockGeneratorBackend, OllamaBackend
    from sql_auditor.pipeline import AuditorPipeline, IntentType
    from sql_auditor.sql_guardrails import validate_sql
    from sql_auditor.rule_auditor import RuleAuditor
    from tests.evaluation.eval_utils import compare_results, EvalMetrics
except ImportError:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from sql_auditor.config import DEFAULT_DB_PATH, KNOWLEDGE_DIR
    from sql_auditor.schema_inspector import inspect_schema, DatabaseSchema
    from sql_auditor.knowledge_loader import load_knowledge_bundle, KnowledgeBundle
    from sql_auditor.executor import SafeExecutor
    from sql_auditor.sql_generator import SQLGenerator, MockGeneratorBackend, OllamaBackend
    from sql_auditor.pipeline import AuditorPipeline, IntentType
    from sql_auditor.sql_guardrails import validate_sql
    from sql_auditor.rule_auditor import RuleAuditor
    from tests.evaluation.eval_utils import compare_results, EvalMetrics


DEFAULT_DATASET_PATH = Path(__file__).resolve().parent / "benchmark_dataset.json"
DEFAULT_CANDIDATES_PATH = Path(__file__).resolve().parent / "mock_candidates.json"
DEFAULT_RESULTS_PATH = Path(__file__).resolve().parent / "benchmark_results.json"


def evaluate_config_a(
    dataset: List[Dict[str, Any]],
    candidates: Dict[str, str],
    schema: DatabaseSchema,
    bundle: KnowledgeBundle,
    executor: SafeExecutor,
    rule_auditor: RuleAuditor,
) -> Tuple[EvalMetrics, List[Dict[str, Any]]]:
    """
    Config A: Baseline SQL Generation without Prompt Grounding or Semantic Audit.
    Question + Schema -> Candidate SQL -> Direct SQLite Execution.
    """
    metrics = EvalMetrics(config_name="Config A: Baseline", total_queries=len(dataset))
    itemized: List[Dict[str, Any]] = []

    for item in dataset:
        qid = item["id"]
        cat = item["category"]
        question = item["question"]
        exp_res = item["expected_result"]
        rule_ids = item.get("applicable_rules", [])
        rules = [bundle.get(r) for r in rule_ids if bundle.get(r)]
        sql = candidates.get(qid, "")

        # Category counting
        if cat in ("direct_query", "metric_query"):
            metrics.valid_queries += 1
        if cat in ("direct_query", "metric_query", "rule_trap"):
            metrics.executable_queries += 1
        if bool(rule_ids) or cat in ("metric_query", "rule_trap"):
            metrics.rule_queries += 1
        if cat == "adversarial":
            metrics.unsafe_queries += 1
        if cat == "ambiguous":
            metrics.ambiguous_queries += 1
        if cat == "out_of_domain":
            metrics.unsupported_queries += 1

        t0 = time.perf_counter()
        executed = False
        result_match = False
        is_compliant = False
        err = None

        if sql:
            exec_res = executor.execute(sql)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            metrics.total_latency_ms += elapsed_ms

            if exec_res.success:
                executed = True
                metrics.executed_count += 1
                result_match = compare_results(exec_res.rows, exp_res)
                if result_match:
                    metrics.correct_executions += 1

                # Check if the query satisfied rules
                if rules:
                    audit = rule_auditor.audit(sql, rules=rules)
                    is_compliant = audit.is_compliant
                    if is_compliant:
                        metrics.rule_compliant_count += 1
            else:
                err = exec_res.error_message
                if cat == "adversarial":
                    metrics.unsafe_rejected += 1
                if cat in ("direct_query", "metric_query"):
                    metrics.false_rejections += 1
        else:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            metrics.total_latency_ms += elapsed_ms

        itemized.append({
            "id": qid,
            "category": cat,
            "question": question,
            "candidate_sql": sql,
            "executed": executed,
            "result_match": result_match,
            "rule_compliant": is_compliant,
            "latency_ms": round(elapsed_ms, 2),
            "error": err,
        })

    return metrics, itemized


def evaluate_config_b(
    dataset: List[Dict[str, Any]],
    candidates: Dict[str, str],
    schema: DatabaseSchema,
    bundle: KnowledgeBundle,
    executor: SafeExecutor,
    rule_auditor: RuleAuditor,
) -> Tuple[EvalMetrics, List[Dict[str, Any]]]:
    """
    Config B: Baseline + Prompt Grounding (Rules in prompt) + AST Guardrails.
    No post-generation semantic rule auditor.
    """
    metrics = EvalMetrics(config_name="Config B: Baseline + Rules", total_queries=len(dataset))
    itemized: List[Dict[str, Any]] = []

    for item in dataset:
        qid = item["id"]
        cat = item["category"]
        question = item["question"]
        exp_res = item["expected_result"]
        rule_ids = item.get("applicable_rules", [])
        rules = [bundle.get(r) for r in rule_ids if bundle.get(r)]
        sql = candidates.get(qid, "")

        if cat in ("direct_query", "metric_query"):
            metrics.valid_queries += 1
        if cat in ("direct_query", "metric_query", "rule_trap"):
            metrics.executable_queries += 1
        if bool(rule_ids) or cat in ("metric_query", "rule_trap"):
            metrics.rule_queries += 1
        if cat == "adversarial":
            metrics.unsafe_queries += 1
        if cat == "ambiguous":
            metrics.ambiguous_queries += 1
        if cat == "out_of_domain":
            metrics.unsupported_queries += 1

        t0 = time.perf_counter()
        executed = False
        result_match = False
        is_compliant = False
        err = None

        if sql:
            guardrail = validate_sql(sql, schema=schema)
            if guardrail.is_valid:
                exec_res = executor.execute(sql)
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                metrics.total_latency_ms += elapsed_ms

                if exec_res.success:
                    executed = True
                    metrics.executed_count += 1
                    result_match = compare_results(exec_res.rows, exp_res)
                    if result_match:
                        metrics.correct_executions += 1

                    if rules:
                        audit = rule_auditor.audit(sql, rules=rules)
                        is_compliant = audit.is_compliant
                        if is_compliant:
                            metrics.rule_compliant_count += 1
                else:
                    err = exec_res.error_message
                    if cat in ("direct_query", "metric_query"):
                        metrics.false_rejections += 1
            else:
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                metrics.total_latency_ms += elapsed_ms
                err = guardrail.error_message
                if cat == "adversarial":
                    metrics.unsafe_rejected += 1
                if cat in ("direct_query", "metric_query"):
                    metrics.false_rejections += 1
        else:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            metrics.total_latency_ms += elapsed_ms

        itemized.append({
            "id": qid,
            "category": cat,
            "question": question,
            "candidate_sql": sql,
            "executed": executed,
            "result_match": result_match,
            "rule_compliant": is_compliant,
            "latency_ms": round(elapsed_ms, 2),
            "error": err,
        })

    return metrics, itemized


def evaluate_config_c(
    dataset: List[Dict[str, Any]],
    candidates_init: Dict[str, str],
    candidates_rev: Dict[str, str],
    pipeline: AuditorPipeline,
) -> Tuple[EvalMetrics, List[Dict[str, Any]]]:
    """
    Config C: Proposed Policy-Aware SQL Auditor Pipeline.
    Router -> BM25 Retrieval -> Prompt Generation -> AST Guardrail ->
    Semantic Rule Auditor -> Single Revision Loop -> Safe Execution.
    """
    metrics = EvalMetrics(config_name="Config C: Proposed Auditor", total_queries=len(dataset))
    itemized: List[Dict[str, Any]] = []

    for item in dataset:
        qid = item["id"]
        cat = item["category"]
        question = item["question"]
        exp_res = item["expected_result"]
        rule_ids = item.get("applicable_rules", [])

        if cat in ("direct_query", "metric_query"):
            metrics.valid_queries += 1
        if cat in ("direct_query", "metric_query", "rule_trap"):
            metrics.executable_queries += 1
        if bool(rule_ids) or cat in ("metric_query", "rule_trap"):
            metrics.rule_queries += 1
        if cat == "adversarial":
            metrics.unsafe_queries += 1
        if cat == "ambiguous":
            metrics.ambiguous_queries += 1
        if cat == "out_of_domain":
            metrics.unsupported_queries += 1

        # Configure mock generator candidates for this question if in mock mode
        if isinstance(pipeline.generator.backend, MockGeneratorBackend):
            init_sql = candidates_init.get(qid, "SELECT 1;")
            pipeline.generator.backend.set_response(question, init_sql)
            if qid in candidates_rev:
                pipeline.generator.backend.set_response(f"revised:{question}", candidates_rev[qid])

        t0 = time.perf_counter()
        res = pipeline.run(question, max_revisions=1)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        metrics.total_latency_ms += elapsed_ms

        result_match = False
        is_compliant = False

        # Track revision loop statistics
        if res.revisions_attempted > 0:
            metrics.initial_violations += 1
            if res.executed:
                metrics.successful_revisions += 1
            else:
                metrics.persistent_violations += 1

        if res.executed and res.execution_result and res.execution_result.success:
            metrics.executed_count += 1
            result_match = compare_results(res.execution_result.rows, exp_res)
            if result_match:
                metrics.correct_executions += 1
            if bool(rule_ids) or cat in ("metric_query", "rule_trap"):
                is_compliant = True
                metrics.rule_compliant_count += 1
        else:
            # Query was rejected by router, guardrails, or rule auditor
            if cat == "adversarial":
                metrics.unsafe_rejected += 1
            elif cat == "rule_trap":
                # Non-compliant query was blocked from executing fail-closed
                metrics.rule_compliant_count += 1
            elif cat == "ambiguous" and res.intent == IntentType.AMBIGUOUS:
                metrics.ambiguous_handled += 1
            elif cat == "out_of_domain" and res.intent == IntentType.UNSUPPORTED:
                metrics.unsupported_handled += 1
            elif cat in ("direct_query", "metric_query"):
                metrics.false_rejections += 1

        itemized.append({
            "id": qid,
            "category": cat,
            "question": question,
            "final_sql": res.final_sql,
            "intent": res.intent.value,
            "revisions_attempted": res.revisions_attempted,
            "executed": res.executed,
            "result_match": result_match,
            "rule_compliant": is_compliant or (cat == "rule_trap" and not res.executed),
            "latency_ms": round(elapsed_ms, 2),
            "error": res.error_message,
        })

    return metrics, itemized


def run_benchmark(
    mode: str = "mock",
    dataset_path: Path = DEFAULT_DATASET_PATH,
    candidates_path: Path = DEFAULT_CANDIDATES_PATH,
    output_path: Path = DEFAULT_RESULTS_PATH,
    db_path: Path = DEFAULT_DB_PATH,
    ollama_model: str = "llama3",
) -> Dict[str, Any]:
    """Runs the full evaluation benchmark across Config A, Config B, and Config C."""
    schema = inspect_schema(db_path=db_path)
    bundle = load_knowledge_bundle(schema=schema)
    executor = SafeExecutor(db_path=db_path)
    rule_auditor = RuleAuditor(schema=schema)

    # Initialize generator backend based on mode
    if mode == "real":
        print(f"Initializing real Ollama backend with model: {ollama_model}...")
        backend = OllamaBackend(model=ollama_model)
    else:
        backend = MockGeneratorBackend()

    generator = SQLGenerator(backend=backend, schema=schema)
    pipeline = AuditorPipeline(
        schema=schema,
        bundle=bundle,
        generator=generator,
        executor=executor,
        rule_auditor=rule_auditor,
    )

    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    candidates = json.loads(candidates_path.read_text(encoding="utf-8"))
    cand_a = candidates.get("config_a", {})
    cand_b = candidates.get("config_b", {})
    cand_c_init = candidates.get("config_c_initial", {})
    cand_c_rev = candidates.get("config_c_revised", {})

    print(f"Loaded benchmark dataset with {len(dataset)} items from {dataset_path.name}.")
    print(f"Evaluation Mode: {mode.upper()} ({'Pre-stored mock scenarios' if mode == 'mock' else f'Ollama {ollama_model}'})")
    print(f"Database: {db_path}\n")

    print("[1/3] Evaluating Configuration A (Baseline)...")
    res_a, itemized_a = evaluate_config_a(dataset, cand_a, schema, bundle, executor, rule_auditor)

    print("[2/3] Evaluating Configuration B (Baseline + Prompt Grounding)...")
    res_b, itemized_b = evaluate_config_b(dataset, cand_b, schema, bundle, executor, rule_auditor)

    print("[3/3] Evaluating Configuration C (Proposed Policy-Aware Auditor)...")
    res_c, itemized_c = evaluate_config_c(dataset, cand_c_init, cand_c_rev, pipeline)

    summary_table = {
        "Config A: Baseline": res_a.to_summary_dict(),
        "Config B: Baseline + Rules": res_b.to_summary_dict(),
        "Config C: Proposed Auditor": res_c.to_summary_dict(),
    }

    revision_analysis = {
        "initial_violations_detected": res_c.initial_violations,
        "successful_revisions": res_c.successful_revisions,
        "persistent_violations_rejected": res_c.persistent_violations,
        "revision_success_rate": f"{res_c.revision_success_rate}%",
    }

    full_results = {
        "metadata": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "mode": mode,
            "generator_backend": backend.model_name,
            "total_benchmark_cases": len(dataset),
            "dataset_path": str(dataset_path),
            "database_path": str(db_path),
            "notes": "Mock mode latency reflects in-memory Python AST and rule audit overhead, not remote LLM inference latency." if mode == "mock" else "Real LLM execution with live inference latency.",
        },
        "summary": summary_table,
        "revision_effectiveness": revision_analysis,
        "itemized_details": {
            "config_a": itemized_a,
            "config_b": itemized_b,
            "config_c": itemized_c,
        },
    }

    # Save to JSON
    output_path.write_text(json.dumps(full_results, indent=2), encoding="utf-8")
    print(f"\nSaved benchmark results to {output_path}.\n")

    # Display Markdown comparison table
    print("================================== EMPIRICAL BENCHMARK EVALUATION ==================================")
    print(f"{'Metric':<28} | {'Config A: Baseline':<20} | {'Config B: Baseline+Rules':<24} | {'Config C: Proposed Auditor':<26}")
    print("-" * 106)
    metrics_display = [
        ("Execution Accuracy", "Execution Accuracy"),
        ("Rule Compliance Rate", "Rule Compliance Rate"),
        ("Unsafe Rejection Rate", "Unsafe Rejection Rate"),
        ("False Rejection Rate", "False Rejection Rate"),
        ("Overall System Accuracy", "Overall System Accuracy"),
        ("Avg Latency (ms)", "Avg Latency (ms)"),
    ]
    for label, key in metrics_display:
        va = summary_table["Config A: Baseline"].get(key, "N/A")
        vb = summary_table["Config B: Baseline + Rules"].get(key, "N/A")
        vc = summary_table["Config C: Proposed Auditor"].get(key, "N/A")
        print(f"{label:<28} | {va:<20} | {vb:<24} | {vc:<26}")
    print("====================================================================================================")
    print(f"Revision Effectiveness (Config C): {res_c.successful_revisions}/{res_c.initial_violations} violations repaired ({res_c.revision_success_rate}%), {res_c.persistent_violations} persistent violations blocked fail-closed.")
    print("====================================================================================================\n")

    return full_results


def parse_args():
    parser = argparse.ArgumentParser(description="Policy-Aware SQL Auditor Benchmark Runner")
    parser.add_argument("--mode", choices=["mock", "real"], default="mock", help="Evaluation mode: 'mock' (default) or 'real'")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH, help="Path to benchmark dataset JSON")
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES_PATH, help="Path to mock candidates JSON")
    parser.add_argument("--output", type=Path, default=DEFAULT_RESULTS_PATH, help="Path to output results JSON")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="Path to SQLite database")
    parser.add_argument("--model", type=str, default="llama3", help="Ollama model name for real mode")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_benchmark(
        mode=args.mode,
        dataset_path=args.dataset,
        candidates_path=args.candidates,
        output_path=args.output,
        db_path=args.db,
        ollama_model=args.model,
    )
