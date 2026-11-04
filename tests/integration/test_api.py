"""
Integration tests for FastAPI endpoints (api.py).
"""

from fastapi.testclient import TestClient
import pytest
from sql_auditor.api import create_app
from sql_auditor.config import DEFAULT_DB_PATH, KNOWLEDGE_DIR
from sql_auditor.schema_inspector import inspect_schema
from sql_auditor.knowledge_loader import load_knowledge_bundle
from sql_auditor.executor import SafeExecutor
from sql_auditor.sql_generator import SQLGenerator, MockGeneratorBackend
from sql_auditor.pipeline import AuditorPipeline
from sql_auditor.audit_log import AuditLogger


@pytest.fixture
def client(tmp_path):
    test_db = tmp_path / "test_api_auditor.db"
    # Copy or use live schema
    schema = inspect_schema(DEFAULT_DB_PATH)
    bundle = load_knowledge_bundle(KNOWLEDGE_DIR, schema=schema)
    executor = SafeExecutor(DEFAULT_DB_PATH)

    backend = MockGeneratorBackend(
        responses={
            "department spend in 2024": (
                "SELECT d.name, sum(e.amount) as spend "
                "FROM departments d JOIN expenses e ON d.id = e.department_id "
                "WHERE e.status = 'approved' AND e.expense_date BETWEEN '2024-01-01' AND '2024-12-31' "
                "GROUP BY d.name;"
            ),
            "drop table": "DROP TABLE departments;",
        }
    )
    generator = SQLGenerator(backend=backend, schema=schema)
    pipeline = AuditorPipeline(schema=schema, bundle=bundle, generator=generator, executor=executor)
    logger = AuditLogger(db_path=test_db)

    app = create_app(pipeline=pipeline, logger=logger, db_path=DEFAULT_DB_PATH)
    return TestClient(app)


def test_health_endpoint(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["tables_count"] >= 5
    assert "departments" in data["tables"]
    assert data["concepts_loaded"] >= 9


def test_rules_endpoint(client):
    resp = client.get("/rules")
    assert resp.status_code == 200
    rules = resp.json()
    assert len(rules) >= 8
    rule_ids = [r["id"] for r in rules]
    assert "metric.departmental_spend" in rule_ids
    assert "policy.fiscal_year" in rule_ids


def test_ask_valid_question(client):
    payload = {"question": "What was department spend in 2024?"}
    resp = client.post("/ask", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["row_count"] > 0
    assert "metric.departmental_spend@v1" in data["cited_rules"]
    assert data["request_id"] is not None


def test_ask_ambiguous_question(client):
    payload = {"question": "spend"}
    resp = client.post("/ask", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ambiguous"
    assert data["clarification_prompt"] is not None


def test_ask_guardrail_rejection(client):
    payload = {"question": "Please drop table departments for 2024"}
    resp = client.post("/ask", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "rejected_guardrail_violation"


def test_audit_logs_retrieval(client):
    # Submit 2 questions to populate logs
    client.post("/ask", json={"question": "What was department spend in 2024?"})
    client.post("/ask", json={"question": "spend"})

    resp = client.get("/audit-logs?limit=10")
    assert resp.status_code == 200
    logs = resp.json()
    assert len(logs) >= 2
    questions = [l["question"] for l in logs]
    assert "What was department spend in 2024?" in questions

