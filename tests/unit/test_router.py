"""
Unit tests for Intent Router (router.py).
"""

import pytest
from sql_auditor.config import KNOWLEDGE_DIR
from sql_auditor.schema_inspector import inspect_schema
from sql_auditor.knowledge_loader import load_knowledge_bundle
from sql_auditor.retrieval import BM25Retriever
from sql_auditor.router import IntentRouter, IntentType


@pytest.fixture(scope="module")
def router():
    schema = inspect_schema()
    bundle = load_knowledge_bundle(knowledge_dir=KNOWLEDGE_DIR, schema=schema)
    retriever = BM25Retriever(bundle=bundle)
    return IntentRouter(bundle=bundle, retriever=retriever)


def test_classify_metric_query(router):
    classification = router.classify("What was the departmental spend for Engineering in 2024?")
    assert classification.intent == IntentType.METRIC_QUERY
    assert classification.confidence > 0.5
    assert "metric.departmental_spend" in classification.matched_concept_ids
    assert "year:2024" in classification.detected_entities
    assert "department:engineering" in classification.detected_entities


def test_classify_active_customer_query(router):
    classification = router.classify("Find all active customers who made purchases recently")
    assert classification.intent == IntentType.METRIC_QUERY
    assert "metric.active_customer" in classification.matched_concept_ids


def test_classify_policy_check_fiscal_year(router):
    classification = router.classify("What is the policy and definition for fiscal year?")
    assert classification.intent == IntentType.POLICY_CHECK
    assert "policy.fiscal_year" in classification.matched_concept_ids


def test_classify_policy_check_expense(router):
    classification = router.classify("What are the reimbursement rules and approval criteria for expenses?")
    assert classification.intent == IntentType.POLICY_CHECK
    assert "policy.expense_reimbursement" in classification.matched_concept_ids


def test_classify_ambiguous_short_query(router):
    classification = router.classify("spend")
    assert classification.intent == IntentType.AMBIGUOUS
    assert classification.clarification_prompt is not None
    assert "specify" in classification.clarification_prompt.lower() or "broad" in classification.clarification_prompt.lower()


def test_classify_ambiguous_empty(router):
    classification = router.classify("   ")
    assert classification.intent == IntentType.AMBIGUOUS
    assert classification.clarification_prompt is not None


def test_classify_unsupported_out_of_domain(router):
    classification = router.classify("What is the current weather forecast in Paris?")
    assert classification.intent == IntentType.UNSUPPORTED


def test_classify_unsupported_crypto(router):
    classification = router.classify("What is the bitcoin price today?")
    assert classification.intent == IntentType.UNSUPPORTED

