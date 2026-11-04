"""
Lexical Retrieval Module for Policy-Aware SQL Auditor.

Implements pure-Python Okapi BM25 scoring over versioned OKF concepts
(titles, descriptions, tags, tables, and bodies) without external embedding models
or paid API dependencies.
"""

from dataclasses import dataclass
import math
import re
from typing import Dict, List, Optional, Set, Tuple

try:
    from sql_auditor.knowledge_loader import ConceptDefinition, KnowledgeBundle
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from sql_auditor.knowledge_loader import ConceptDefinition, KnowledgeBundle


# Common English stopwords to ignore in lexical matching
STOPWORDS: Set[str] = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and",
    "any", "are", "aren't", "as", "at", "be", "because", "been", "before", "being",
    "below", "between", "both", "but", "by", "can", "can't", "cannot", "could",
    "couldn't", "did", "didn't", "do", "does", "doesn't", "doing", "don't", "down",
    "during", "each", "few", "for", "from", "further", "had", "hadn't", "has",
    "hasn't", "have", "haven't", "having", "he", "he'd", "he'll", "he's", "her",
    "here", "here's", "hers", "herself", "him", "himself", "his", "how", "how's",
    "i", "i'd", "i'll", "i'm", "i've", "if", "in", "into", "is", "isn't", "it",
    "it's", "its", "itself", "let's", "me", "more", "most", "mustn't", "my",
    "myself", "no", "nor", "not", "of", "off", "on", "once", "only", "or", "other",
    "ought", "our", "ours", "ourselves", "out", "over", "own", "same", "shan't",
    "she", "she'd", "she'll", "she's", "should", "shouldn't", "so", "some", "such",
    "than", "that", "that's", "the", "their", "theirs", "them", "themselves",
    "then", "there", "there's", "these", "they", "they'd", "they'll", "they're",
    "they've", "this", "those", "through", "to", "too", "under", "until", "up",
    "very", "was", "wasn't", "we", "we'd", "we'll", "we're", "we've", "were",
    "weren't", "what", "what's", "when", "when's", "where", "where's", "which",
    "while", "who", "who's", "whom", "why", "why's", "with", "won't", "would",
    "wouldn't", "you", "you'd", "you'll", "you're", "you've", "your", "yours",
    "yourself", "yourselves", "show", "give", "list", "tell", "find", "get", "many",
}


def tokenize(text: str) -> List[str]:
    """Tokenizes text into lowercase alphanumeric terms, stripping stopwords."""
    words = re.findall(r"[a-zA-Z0-9_]+", text.lower())
    return [w for w in words if w not in STOPWORDS and len(w) > 1]


@dataclass
class ScoredConcept:
    concept: ConceptDefinition
    score: float
    matched_terms: List[str]


class BM25Retriever:
    """
    Pure-Python Okapi BM25 retriever for OKF concepts.
    Standard parameters: k1 = 1.5, b = 0.75.
    """

    def __init__(
        self,
        bundle: KnowledgeBundle,
        k1: float = 1.5,
        b: float = 0.75,
    ):
        self.bundle = bundle
        self.k1 = k1
        self.b = b
        self.docs: List[Tuple[str, List[str]]] = []  # (concept_id, token_list)
        self.doc_lens: Dict[str, int] = {}
        self.avg_doc_len: float = 0.0
        self.df: Dict[str, int] = {}  # document frequency per term
        self.idf: Dict[str, float] = {}

        self._build_index()

    def _build_index(self) -> None:
        """Constructs inverted index and term statistics over all concepts."""
        total_len = 0
        concepts = [c for c in self.bundle.get_all() if c.type != "index"]

        for c in concepts:
            # Weighted document representation:
            # Title tokens repeated 3x, tags 2x, tables 2x for relevance boost
            title_tokens = tokenize(c.title) * 3
            tag_tokens = tokenize(" ".join(c.tags)) * 2
            table_tokens = tokenize(" ".join(c.tables)) * 2
            desc_tokens = tokenize(c.description)
            body_tokens = tokenize(c.body)

            all_tokens = title_tokens + tag_tokens + table_tokens + desc_tokens + body_tokens
            self.docs.append((c.id, all_tokens))
            self.doc_lens[c.id] = len(all_tokens)
            total_len += len(all_tokens)

            unique_terms = set(all_tokens)
            for t in unique_terms:
                self.df[t] = self.df.get(t, 0) + 1

        n_docs = len(self.docs)
        self.avg_doc_len = total_len / n_docs if n_docs > 0 else 0.0

        # Calculate Okapi BM25 IDF
        for t, freq in self.df.items():
            self.idf[t] = math.log((n_docs - freq + 0.5) / (freq + 0.5) + 1.0)

    def retrieve(
        self,
        query: str,
        top_k: int = 4,
        expand_related: bool = True,
    ) -> List[ScoredConcept]:
        """
        Retrieves top-k most relevant OKF concepts for a user question.

        Args:
            query: The user query string.
            top_k: Maximum concepts to return.
            expand_related: If True, automatically pulls in linked policies/rules.

        Returns:
            List of ScoredConcept ranked by BM25 score descending.
        """
        query_terms = tokenize(query)
        if not query_terms:
            return []

        scores: Dict[str, float] = {}
        matched_terms_map: Dict[str, List[str]] = {}

        for cid, doc_tokens in self.docs:
            score = 0.0
            matched = []
            doc_len = self.doc_lens[cid]

            # Term frequency map in current document
            tf: Dict[str, int] = {}
            for token in doc_tokens:
                tf[token] = tf.get(token, 0) + 1

            for qterm in query_terms:
                if qterm in tf:
                    matched.append(qterm)
                    term_freq = tf[qterm]
                    idf_val = self.idf.get(qterm, 0.0)

                    # Okapi BM25 formula
                    numerator = term_freq * (self.k1 + 1)
                    denominator = term_freq + self.k1 * (1 - self.b + self.b * (doc_len / self.avg_doc_len))
                    score += idf_val * (numerator / denominator)

            if score > 0:
                scores[cid] = score
                matched_terms_map[cid] = list(set(matched))

        # Sort concepts by score descending
        ranked_cids = sorted(scores.keys(), key=lambda cid: scores[cid], reverse=True)
        top_cids = ranked_cids[:top_k]

        results = [
            ScoredConcept(
                concept=self.bundle.get(cid),  # type: ignore
                score=round(scores[cid], 3),
                matched_terms=matched_terms_map[cid],
            )
            for cid in top_cids
            if self.bundle.get(cid) is not None
        ]

        # Expand related concepts (e.g. pulling in policy.fiscal_year for departmental_spend)
        if expand_related:
            included_ids = {r.concept.id for r in results}
            extra_concepts = []
            for r in results:
                # Metrics expand to their referenced policies and tables
                if r.concept.type == "metric":
                    for rel_id in r.concept.related_concepts:
                        if rel_id not in included_ids:
                            rel_concept = self.bundle.get(rel_id)
                            if rel_concept:
                                extra_concepts.append(
                                    ScoredConcept(
                                        concept=rel_concept,
                                        score=round(r.score * 0.75, 3),  # Inherited partial score
                                        matched_terms=[f"linked_from:{r.concept.id}"],
                                    )
                                )
                                included_ids.add(rel_id)
            results.extend(extra_concepts)

        return results

