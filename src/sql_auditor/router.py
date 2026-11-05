"""
Intent Router Module for Policy-Aware SQL Auditor.

Classifies incoming user questions into explicit operational intents:
- metric_query: Requests for business calculations, aggregations, or financial reporting.
- policy_check: Inquiries about corporate definitions, rules, or compliance policies.
- ambiguous: Underspecified questions requiring user clarification before generation.
- unsupported: Out-of-scope questions, prompt injections, or DDL/arbitrary requests.
"""

from dataclasses import dataclass, field
from enum import Enum
import re
from typing import List, Optional, Set

from sql_auditor.knowledge_loader import KnowledgeBundle
from sql_auditor.retrieval import BM25Retriever, STOPWORDS


class IntentType(str, Enum):
    """Operational categories of user natural-language questions."""

    METRIC_QUERY = "metric_query"
    """Actionable analytical question targeting corporate data or business metrics."""

    POLICY_CHECK = "policy_check"
    """Inquiry asking about business rule definitions, compliance policies, or audit criteria."""

    AMBIGUOUS = "ambiguous"
    """Underspecified query missing required parameters (e.g. fiscal year, department)."""

    UNSUPPORTED = "unsupported"
    """Out-of-domain topic, external inquiry, or unauthorized query."""


@dataclass
class IntentClassification:
    """Outcome of intent routing and entity detection.

    Attributes:
        intent: Classified operational intent category.
        confidence: Numeric confidence score between 0.0 and 1.0.
        matched_concept_ids: IDs of OKF concepts matching the query.
        detected_entities: Specific extracted filters/entities (e.g., 'year:2024', 'department:engineering').
        clarification_prompt: Clarification question if intent is ambiguous or unsupported.
        reason: Diagnostic reasoning explaining why the intent was assigned.
    """

    intent: IntentType
    confidence: float
    matched_concept_ids: List[str] = field(default_factory=list)
    detected_entities: List[str] = field(default_factory=list)
    clarification_prompt: Optional[str] = None
    reason: str = ""


# Keywords indicative of policy inquiries
POLICY_KEYWORDS: Set[str] = {
    "policy", "rule", "rules", "definition", "define", "guideline", "guidelines",
    "requirement", "requirements", "criteria", "standard", "how is", "what is the policy",
}

# Known enterprise departments for entity extraction
KNOWN_DEPARTMENTS: Set[str] = {
    "engineering", "marketing", "human resources", "hr", "legal",
    "compliance", "product design", "design",
}

# Domains explicitly identified as out-of-scope for the corporate database
UNSUPPORTED_DOMAINS: Set[str] = {
    "weather", "president", "ceo", "stock", "stocks", "bitcoin", "crypto",
    "music", "joke", "recipe", "flight", "hotel", "python script", "translate",
}


class IntentRouter:
    """Classifies user natural-language questions and flags ambiguity early.

    Operates a 5-step heuristic pipeline:
    1. Out-of-domain detection (flags UNSUPPORTED domains).
    2. Entity extraction (extracts years, departments, statuses).
    3. Policy check detection (flags inquiries about business rules).
    4. Ambiguity detection (flags underspecified queries lacking time or grouping boundaries).
    5. Metric relevance scoring (matches queries against OKF concepts using BM25).
    """

    def __init__(
        self,
        bundle: Optional[KnowledgeBundle] = None,
        retriever: Optional[BM25Retriever] = None,
    ):
        """Initializes the IntentRouter with an optional knowledge bundle and lexical retriever.

        Args:
            bundle: Optional KnowledgeBundle containing business rules.
            retriever: Optional BM25Retriever instance; constructed from bundle if not supplied.
        """
        self.bundle = bundle
        self.retriever = retriever or (BM25Retriever(bundle) if bundle else None)

    def classify(self, query: str) -> IntentClassification:
        """Evaluates a user question and assigns an operational intent.

        Args:
            query: Raw user query string.

        Returns:
            IntentClassification containing intent type, confidence, entities, and rationale.
        """
        cleaned = query.strip()
        if not cleaned:
            return IntentClassification(
                intent=IntentType.AMBIGUOUS,
                confidence=1.0,
                clarification_prompt="The query was empty. Please provide a business question or metric inquiry.",
                reason="Empty input string.",
            )

        q_lower = cleaned.lower()

        # 1. Check for completely unsupported / out-of-scope topics
        for word in re.findall(r"\w+", q_lower):
            if word in UNSUPPORTED_DOMAINS:
                return IntentClassification(
                    intent=IntentType.UNSUPPORTED,
                    confidence=0.95,
                    reason=f"Detected out-of-domain topic: '{word}'.",
                    clarification_prompt="This system only supports queries regarding corporate departments, budgets, expenses, customers, and orders.",
                )

        # 2. Extract detected entities (years, department names, statuses)
        detected_entities = []
        years = re.findall(r"\b(20\d\d)\b", cleaned)
        detected_entities.extend([f"year:{y}" for y in years])

        for dept in KNOWN_DEPARTMENTS:
            if re.search(r"\b" + re.escape(dept) + r"\b", q_lower):
                detected_entities.append(f"department:{dept}")

        for status in ("approved", "pending", "rejected", "completed", "cancelled"):
            if re.search(r"\b" + re.escape(status) + r"\b", q_lower):
                detected_entities.append(f"status:{status}")

        # Retrieve relevant concepts via BM25 if available
        matched_concept_ids = []
        top_score = 0.0
        if self.retriever:
            retrieved = self.retriever.retrieve(cleaned, top_k=3, expand_related=False)
            matched_concept_ids = [r.concept.id for r in retrieved]
            top_score = retrieved[0].score if retrieved else 0.0

        # 3. Check for Policy / Rule Definition queries
        has_policy_kw = any(re.search(r"\b" + re.escape(kw) + r"\b", q_lower) for kw in POLICY_KEYWORDS)
        if has_policy_kw:
            return IntentClassification(
                intent=IntentType.POLICY_CHECK,
                confidence=0.9,
                matched_concept_ids=matched_concept_ids,
                detected_entities=detected_entities,
                reason="Question specifically inquires about rules, policies, or definitions.",
            )

        # 4. Check for Ambiguous / Underspecified inputs
        # Queries lacking actionable specifics (e.g. "spend", "show expenses", "customers", "show me the spend")
        words = q_lower.split()
        content_words = [w for w in re.findall(r"[a-zA-Z0-9_]+", q_lower) if w not in STOPWORDS]
        has_dimension = any(e.startswith("year:") or e.startswith("department:") for e in detected_entities)
        if (len(words) <= 2 or len(content_words) <= 1) and not has_dimension:
            clarification = (
                "Your question is too broad. Please specify the target fiscal year (e.g. 2024) "
                "or department (e.g. Engineering) to compute this metric accurately."
            )
            return IntentClassification(
                intent=IntentType.AMBIGUOUS,
                confidence=0.85,
                matched_concept_ids=matched_concept_ids,
                detected_entities=detected_entities,
                clarification_prompt=clarification,
                reason="Query is underspecified (missing time boundary or grouping dimension).",
            )

        # 5. Check if query matches known metrics/tables with sufficient relevance
        if matched_concept_ids and top_score > 0.5:
            return IntentClassification(
                intent=IntentType.METRIC_QUERY,
                confidence=min(round(0.5 + (top_score / 10.0), 2), 0.98),
                matched_concept_ids=matched_concept_ids,
                detected_entities=detected_entities,
                reason="Successfully matched supported business metrics and schema entities.",
            )

        # Fallback if no concepts matched or very low relevance
        return IntentClassification(
            intent=IntentType.UNSUPPORTED,
            confidence=0.7,
            reason="Could not match query to any supported corporate metrics, policies, or tables.",
            clarification_prompt="Unable to map your request to supported financial or customer data.",
        )
