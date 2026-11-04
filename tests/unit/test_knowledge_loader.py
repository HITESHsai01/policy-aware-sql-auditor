"""
Unit tests for OKF Knowledge Loader and Validator (knowledge_loader.py).
"""

from pathlib import Path
import pytest
from sql_auditor.config import KNOWLEDGE_DIR
from sql_auditor.schema_inspector import DatabaseSchema, TableInfo, ColumnInfo, inspect_schema
from sql_auditor.knowledge_loader import (
    load_knowledge_bundle,
    parse_concept_file,
    KnowledgeValidationError,
    RequiredFilter,
    RequiredJoin,
    ForbiddenSubstitute,
)


@pytest.fixture(scope="module")
def schema():
    return inspect_schema()


@pytest.fixture(scope="module")
def bundle(schema):
    return load_knowledge_bundle(knowledge_dir=KNOWLEDGE_DIR, schema=schema)


def test_bundle_contains_all_core_concepts(bundle):
    assert bundle.get("metric.departmental_spend") is not None
    assert bundle.get("metric.active_customer") is not None
    assert bundle.get("policy.expense_reimbursement") is not None
    assert bundle.get("policy.fiscal_year") is not None
    assert bundle.get("table.departments") is not None
    assert bundle.get("table.budgets") is not None
    assert bundle.get("table.expenses") is not None
    assert bundle.get("table.customers") is not None
    assert bundle.get("table.orders") is not None
    assert bundle.get("index") is not None


def test_metric_departmental_spend_structure(bundle):
    metric = bundle.get("metric.departmental_spend")
    assert metric.version >= 1
    assert metric.type == "metric"
    assert "expenses" in metric.tables
    assert "departments" in metric.tables
    assert "policy.fiscal_year" in metric.related_concepts

    # Check required filters
    status_filter = next((f for f in metric.required_filters if f.column == "expenses.status"), None)
    assert status_filter is not None
    assert status_filter.operator == "="
    assert status_filter.value == "approved"

    # Check required joins
    assert len(metric.required_joins) >= 1
    assert metric.required_joins[0].from_table == "departments"
    assert metric.required_joins[0].to_table == "expenses"


def test_metric_active_customer_forbidden_substitute(bundle):
    metric = bundle.get("metric.active_customer")
    assert metric.type == "metric"
    assert len(metric.forbidden_substitutes) >= 1
    sub = metric.forbidden_substitutes[0]
    assert sub.column == "customers.is_active"
    assert "legacy" in sub.reason.lower()


def test_bundle_lookups(bundle):
    tables = bundle.list_by_type("table")
    assert len(tables) == 5

    metrics = bundle.list_by_type("metric")
    assert len(metrics) == 2

    expense_concepts = bundle.list_by_table("expenses")
    cids = [c.id for c in expense_concepts]
    assert "metric.departmental_spend" in cids
    assert "table.expenses" in cids


def test_validation_fails_on_hallucinated_table(tmp_path, schema):
    bad_concept_content = """---
id: metric.fake_metric
version: 1
type: metric
title: Fake Metric
description: Metric referencing non-existent table.
tags: []
tables:
  - non_existent_table
related_concepts: []
---
Body text
"""
    f = tmp_path / "bad.md"
    f.write_text(bad_concept_content, encoding="utf-8")

    with pytest.raises(KnowledgeValidationError) as exc_info:
        load_knowledge_bundle(knowledge_dir=tmp_path, schema=schema)
    assert "non_existent_table" in str(exc_info.value)


def test_validation_fails_on_hallucinated_column(tmp_path, schema):
    bad_concept_content = """---
id: metric.bad_col
version: 1
type: metric
title: Bad Column Metric
description: Metric referencing non-existent column in valid table.
tags: []
tables:
  - expenses
related_concepts: []
required_filters:
  - column: expenses.non_existent_column
    operator: "="
    value: "test"
---
Body text
"""
    f = tmp_path / "bad_col.md"
    f.write_text(bad_concept_content, encoding="utf-8")

    with pytest.raises(KnowledgeValidationError) as exc_info:
        load_knowledge_bundle(knowledge_dir=tmp_path, schema=schema)
    assert "non_existent_column" in str(exc_info.value)


def test_validation_fails_on_unresolved_related_concept(tmp_path, schema):
    bad_concept_content = """---
id: metric.broken_link
version: 1
type: metric
title: Broken Link
description: References missing policy.
tags: []
tables: []
related_concepts:
  - policy.does_not_exist
---
Body text
"""
    f = tmp_path / "broken.md"
    f.write_text(bad_concept_content, encoding="utf-8")

    with pytest.raises(KnowledgeValidationError) as exc_info:
        load_knowledge_bundle(knowledge_dir=tmp_path, schema=schema)
    assert "policy.does_not_exist" in str(exc_info.value)

