"""
SQL Generator Module.

Constructs grounded prompts combining:
- User natural language question
- Live database schema
- Retrieved business rules and compliance constraints
- Optional revision feedback from a prior failed rule audit

Interfaces with pluggable model backends:
- MockGeneratorBackend (for deterministic testing and evaluation)
- OllamaBackend (for local LLMs like Llama 3, Qwen-Coder, Mistral)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
import json
import re
from typing import Any, Dict, List, Optional
import urllib.request
import urllib.error

try:
    from sql_auditor.knowledge_loader import ConceptDefinition
    from sql_auditor.schema_inspector import DatabaseSchema
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from sql_auditor.knowledge_loader import ConceptDefinition
    from sql_auditor.schema_inspector import DatabaseSchema


@dataclass
class GenerationResult:
    sql: str
    raw_output: str
    model_name: str
    prompt: str
    attempt: int = 1


class BaseLLMBackend(ABC):
    """Abstract interface for LLM generation backends."""

    @abstractmethod
    def generate(self, prompt: str) -> str:
        """Generates raw text response given a prompt."""
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        pass


class MockGeneratorBackend(BaseLLMBackend):
    """
    Deterministic mock backend for testing, CI/CD, and offline verification.
    Matches queries or revision feedback to canned SQL statements.
    """

    def __init__(self, responses: Optional[Dict[str, str]] = None, default_response: Optional[str] = None):
        self._responses = responses or {}
        self._default_response = default_response or "SELECT 1;"
        self.call_history: List[str] = []

    def set_response(self, key_substring: str, sql: str) -> None:
        self._responses[key_substring.lower()] = sql

    def generate(self, prompt: str) -> str:
        self.call_history.append(prompt)
        p_lower = prompt.lower()

        # Check revision feedback first if present
        if "failed compliance audit" in p_lower:
            for k, resp in self._responses.items():
                if k.startswith("revised:") and k[len("revised:"):].strip().lower() in p_lower:
                    return f"```sql\n{resp}\n```"

        # Check standard matching
        for k, resp in self._responses.items():
            if not k.startswith("revised:") and k in p_lower:
                return f"```sql\n{resp}\n```"

        return f"```sql\n{self._default_response}\n```"

    @property
    def model_name(self) -> str:
        return "mock-generator-v1"


class OllamaBackend(BaseLLMBackend):
    """Backend connecting to a local Ollama instance (e.g. Llama 3, Qwen2.5-Coder)."""

    def __init__(
        self,
        model: str = "llama3",
        base_url: str = "http://localhost:11434",
        timeout_seconds: float = 30.0,
    ):
        self._model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    @property
    def model_name(self) -> str:
        return f"ollama/{self._model}"

    def generate(self, prompt: str) -> str:
        url = f"{self.base_url}/api/generate"
        payload = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.0},
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("response", "")
        except urllib.error.URLError as e:
            raise RuntimeError(f"Failed to connect to Ollama at {url}: {str(e)}")


class SQLGenerator:
    """Manages prompt construction and candidate SQL generation."""

    def __init__(self, backend: BaseLLMBackend, schema: DatabaseSchema):
        self.backend = backend
        self.schema = schema

    def build_prompt(
        self,
        question: str,
        rules: List[ConceptDefinition],
        revision_feedback: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Constructs an audited prompt including schema and business compliance rules."""
        context = context or {}
        lines = [
            "You are an expert SQL developer for SQLite.",
            "Generate ONLY a single valid read-only SQLite SELECT query answering the user question.",
            "Do NOT include explanations, comments, or multiple statements.",
            "",
            "### DATABASE SCHEMA",
            self.schema.to_prompt_str(),
            "",
        ]

        # Add business rules
        if rules:
            lines.append("### MANDATORY BUSINESS RULES & COMPLIANCE POLICIES")
            for r in rules:
                if r.type == "index":
                    continue
                lines.append(f"Rule ID: {r.id} (v{r.version}) - {r.title}")
                lines.append(f"Description: {r.description}")
                for rf in r.required_filters:
                    if rf.type == "fiscal_year_range":
                        lines.append(f"  - MUST filter: {rf.column} within the target fiscal year boundaries (Jan 1 to Dec 31).")
                    elif rf.type == "relative_date_range":
                        lines.append(f"  - MUST filter: {rf.column} within trailing {rf.window_days or 90} days.")
                    elif rf.operator == "=" and rf.value is not None:
                        lines.append(f"  - MUST filter: {rf.column} = '{rf.value}'")
                for fs in r.forbidden_substitutes:
                    lines.append(f"  - FORBIDDEN: Do NOT use '{fs.column}'. Reason: {fs.reason}")
                for rj in r.required_joins:
                    lines.append(f"  - Required Join: {rj.from_table} to {rj.to_table} ON {rj.on}")
            lines.append("")

        if context:
            lines.append(f"Context parameters: {json.dumps(context)}")
            lines.append("")

        # Add revision feedback if previous attempt failed audit
        if revision_feedback:
            lines.append("### PREVIOUS ATTEMPT FAILED COMPLIANCE AUDIT")
            lines.append("Your previous SQL query violated the following business rules:")
            lines.append(revision_feedback)
            lines.append("Fix the query so that ALL violated rules and missing filters are strictly satisfied.")
            lines.append("")

        lines.append(f"User Question: {question}")
        lines.append("Output your final SQL inside a ```sql ... ``` code block.")

        return "\n".join(lines)

    def generate_candidate_sql(
        self,
        question: str,
        rules: List[ConceptDefinition],
        revision_feedback: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        attempt: int = 1,
    ) -> GenerationResult:
        """Builds prompt, invokes backend, and extracts cleaned candidate SQL."""
        prompt = self.build_prompt(
            question=question,
            rules=rules,
            revision_feedback=revision_feedback,
            context=context,
        )
        raw_output = self.backend.generate(prompt)
        extracted_sql = self.extract_sql(raw_output)

        return GenerationResult(
            sql=extracted_sql,
            raw_output=raw_output,
            model_name=self.backend.model_name,
            prompt=prompt,
            attempt=attempt,
        )

    @staticmethod
    def extract_sql(raw_text: str) -> str:
        """Extracts SQL query from markdown code fence or raw text."""
        cleaned = raw_text.strip()
        # Look for ```sql ... ```
        m = re.search(r"```(?:sql)?\s*(.*?)\s*```", cleaned, re.DOTALL | re.IGNORECASE)
        if m:
            sql = m.group(1).strip()
        else:
            sql = cleaned

        # Remove single trailing semicolon if present
        return sql.rstrip(";") + ";"
