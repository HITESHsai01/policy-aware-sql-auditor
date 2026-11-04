"""
Unit tests for BM25 Lexical Retrieval (retrieval.py).
"""

import pytest
from sql_auditor.config import KNOWLEDGE_DIR
from sql_auditor.schema_inspector import inspect_schema
from sql_auditor.knowledge_loader import load_knowledge_bundle
from sql_auditor.retrieval import BM25Retriever, tokenize


@pytest.fixture(scope="module")
def retriever():
    schema = inspect_schema()
    bundle = load_knowledge_bundle(knowledge_dir=KNOWLEDGE_DIR, schema=schema)
    return BM25Retriever(bundle=bundle)


def test_tokenize_filters_stopwords():
    tokens = tokenize("What is the total departmental spend for 2024?")
    assert "what" not in tokens
    assert "is" not in tokens
    assert "the" not in tokens
    assert "for" not in tokens
    assert "spend" in tokens
    assert "departmental" in tokens
    assert "2024" in tokens


def test_retrieve_departmental_spend(retriever):
    results = retriever.retrieve("department spend in 2024", top_k=3, expand_related=True)
    cids = [r.concept.id for r in results]
    assert "metric.departmental_spend" in cids
    # Related concepts expanded
    assert "policy.fiscal_year" in cids
    assert "policy.expense_reimbursement" in cids
    # Top result should be departmental spend
    assert results[0].concept.id == "metric.departmental_spend"
    assert results[0].score > 0


def test_retrieve_active_customers(retriever):
    results = retriever.retrieve("how many active customers do we have?", top_k=3)
    cids = [r.concept.id for r in results]
    assert "metric.active_customer" in cids
    assert results[0].concept.id == "metric.active_customer"
    assert "table.customers" in cids


def test_retrieve_budget_allocation(retriever):
    results = retriever.retrieve("approved budget allocations per department", top_k=2)
    cids = [r.concept.id for r in results]
    assert "table.budgets" in cids or "table.departments" in cids


def test_retrieve_policy_expense(retriever):
    results = retriever.retrieve("reimbursement approval policy guidelines", top_k=2)
    cids = [r.concept.id for r in results]
    assert "policy.expense_reimbursement" in cids


def test_empty_or_stopword_query(retriever):
    res_empty = retriever.retrieve("")
    assert res_empty == []

    res_stopwords = retriever.retrieve("what is it")
    assert res_stopwords == []

