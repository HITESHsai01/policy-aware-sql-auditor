"""
SQL Generator Module for Policy-Aware SQL Auditor.

Constructs grounded prompts combining:
- User natural language question
- Live database schema
- Retrieved business rules and compliance constraints
- Optional revision feedback from prior failed rule audits

Interfaces with pluggable model backends:
- MockGeneratorBackend (for deterministic testing, CI/CD, and evaluation)
- OllamaBackend (for local LLMs like Llama 3, Qwen-Coder, Mistral)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
import json
import re
from typing import Any, Dict, List, Optional
import urllib.error
import urllib.request

from sql_auditor.knowledge_loader import ConceptDefinition
from sql_auditor.schema_inspector import DatabaseSchema


@dataclass
class GenerationResult:
    """Encapsulates the output of a SQL synthesis cycle.

    Attributes:
        sql: Extracted candidate SQL query string.
        raw_output: Unprocessed text emitted by the LLM backend.
        model_name: Name/identifier of the generating LLM backend.
        prompt: Full prompt text submitted to the model.
        attempt: Attempt counter for tracking revision cycles (default: 1).
    """

    sql: str
    raw_output: str
    model_name: str
    prompt: str
    attempt: int = 1


class BaseLLMBackend(ABC):
    """Abstract interface defining required methods for language model generation backends."""

    @abstractmethod
    def generate(self, prompt: str) -> str:
        """Generates raw text response given a prompt.

        Args:
            prompt: Text prompt with instructions, schema, and rules.

        Returns:
            Raw textual completion string from the model.
        """
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Canonical name of the generation backend model."""
        pass


class MockGeneratorBackend(BaseLLMBackend):
    """Deterministic mock backend for testing, CI/CD, and offline verification.

    Matches query keywords or revision feedback phrases against pre-configured SQL statements.
    """

    def __init__(
        self,
        responses: Optional[Dict[str, str]] = None,
        default_response: Optional[str] = None,
    ):
        """Initializes the mock backend.

        Args:
            responses: Dictionary mapping trigger substrings to candidate SQL queries.
            default_response: Fallback SQL query if no trigger substring matches.
        """
        self._responses = responses or {}
        self._default_response = default_response or "SELECT 1;"
        self.call_history: List[str] = []

    @property
    def default_response(self) -> str:
        """Fallback SQL query string."""
        return self._default_response

    @default_response.setter
    def default_response(self, value: str) -> None:
        """Sets the fallback SQL query string."""
        self._default_response = value

    def set_response(self, key_substring: str, sql: str) -> None:
        """Registers a response mapping for a specific prompt substring.

        Args:
            key_substring: Trigger phrase to match (case-insensitive).
            sql: SQL query to return when triggered.
        """
        self._responses[key_substring.lower()] = sql

    def generate(self, prompt: str) -> str:
        """Matches prompt against configured canned responses and records history.

        Args:
            prompt: Generated prompt string.

        Returns:
            Fenced markdown SQL block matching configured response.
        """
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
        """Returns mock generator model identifier."""
        return "mock-generator-v1"


class OllamaBackend(BaseLLMBackend):
    """Backend connecting to a local Ollama instance (e.g. Llama 3, Qwen2.5-Coder)."""

    def __init__(
        self,
        model: str = "llama3.2",
        base_url: str = "http://localhost:11434",
        timeout_seconds: float = 90.0,
    ):
        """Initializes Ollama HTTP client.

        Args:
            model: Model tag registered in local Ollama instance (e.g. 'llama3.2', 'qwen2.5-coder').
            base_url: Base endpoint URL for Ollama service.
            timeout_seconds: HTTP request timeout in seconds (default 90s to accommodate cold model load).
        """
        self._model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    @property
    def model_name(self) -> str:
        """Returns model identifier formatted as 'ollama/<model>'."""
        return f"ollama/{self._model}"

    def generate(self, prompt: str) -> str:
        """Submits prompt to Ollama's /api/generate endpoint.

        Args:
            prompt: Text prompt string.

        Returns:
            Raw response text generated by Ollama.

        Raises:
            RuntimeError: If connection to Ollama fails or times out.
        """
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


class GeminiBackend(BaseLLMBackend):
    """Backend connecting to the Google Gemini REST API (e.g. gemini-2.5-flash, gemini-1.5-flash)."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gemini-2.5-flash",
        timeout_seconds: float = 60.0,
    ):
        """Initializes Gemini API client.

        Args:
            api_key: Google Gemini API key. Falls back to GEMINI_API_KEY environment variable.
            model: Gemini model identifier (default: 'gemini-2.5-flash').
            timeout_seconds: HTTP request timeout in seconds (default: 30s).
        """
        import os
        if api_key is not None:
            self.api_key = api_key
        else:
            self.api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or ""
        self._model = model
        self.timeout_seconds = timeout_seconds

    @property
    def model_name(self) -> str:
        """Returns model identifier formatted as 'gemini/<model>'."""
        return f"gemini/{self._model}"

    def generate(self, prompt: str) -> str:
        """Submits prompt to Google Gemini's generateContent endpoint.

        Args:
            prompt: Text prompt string.

        Returns:
            Raw response text generated by Gemini.

        Raises:
            RuntimeError: If connection fails or API returns an error.
            ValueError: If no API key is provided.
        """
        if not self.api_key:
            raise ValueError(
                "Gemini API key is required. Please set the GEMINI_API_KEY environment variable in your .env file."
            )

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self._model}:generateContent"
        gen_config: Dict[str, Any] = {"temperature": 0.0}
        if "2.5" in self._model:
            gen_config["thinkingConfig"] = {"thinkingBudget": 0}

        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt}
                    ]
                }
            ],
            "generationConfig": gen_config,
        }

        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key,
        }

        def _clean_err(text: str) -> str:
            if self.api_key and self.api_key in text:
                text = text.replace(self.api_key, "[REDACTED]")
            import re
            return re.sub(r"AIza[0-9A-Za-z\-_]{35}", "[REDACTED]", text)

        payload_bytes = json.dumps(payload).encode("utf-8")
        import time
        max_attempts = 3
        for attempt_idx in range(max_attempts):
            req = urllib.request.Request(
                url,
                data=payload_bytes,
                headers=headers,
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    candidates = data.get("candidates", [])
                    if not candidates:
                        return ""
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if not parts:
                        return ""
                    return parts[0].get("text", "")
            except urllib.error.HTTPError as e:
                err_body = e.read().decode("utf-8") if e.fp else str(e)
                # Automatically retry temporary 503 high-demand spikes and 429 rate limits
                if e.code in (503, 429) and attempt_idx < max_attempts - 1:
                    time.sleep(1.5 * (attempt_idx + 1))
                    continue
                try:
                    parsed_err = json.loads(err_body)
                    error_detail = parsed_err.get("error", {}).get("message", err_body)
                except Exception:
                    error_detail = err_body
                raise RuntimeError(_clean_err(f"Gemini API request failed (HTTP {e.code}): {error_detail}"))
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt_idx < max_attempts - 1:
                    time.sleep(1.0)
                    continue
                raise RuntimeError(_clean_err(f"Failed to connect to Gemini API: {str(e)}"))


class SQLGenerator:
    """Manages prompt engineering, compliance context injection, and candidate SQL generation."""

    def __init__(self, backend: BaseLLMBackend, schema: DatabaseSchema):
        """Initializes the generator with a model backend and database schema.

        Args:
            backend: BaseLLMBackend implementation for generating text.
            schema: DatabaseSchema catalog providing live schema context.
        """
        self.backend = backend
        self.schema = schema

    def build_prompt(
        self,
        question: str,
        rules: List[ConceptDefinition],
        revision_feedback: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Constructs an audited prompt including schema and business compliance rules.

        Args:
            question: Natural language question asked by user.
            rules: List of retrieved OKF concepts to inject into the prompt.
            revision_feedback: Optional error feedback from prior failed rule audit.
            context: Optional dictionary of context parameters (e.g., fiscal_year).

        Returns:
            Fully assembled prompt string ready for LLM generation.
        """
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
                        target_y = context.get("fiscal_year") or context.get("year")
                        if target_y:
                            lines.append(
                                f"  - MUST filter: {rf.column} BETWEEN '{target_y}-01-01' AND '{target_y}-12-31' for fiscal year {target_y}."
                            )
                        else:
                            lines.append(
                                f"  - MUST filter: {rf.column} within the target fiscal year boundaries (Jan 1 to Dec 31)."
                            )
                    elif rf.type == "relative_date_range":
                        lines.append(
                            f"  - MUST filter: {rf.column} within trailing {rf.window_days or 90} days."
                        )
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
        """Builds prompt, invokes model backend, and extracts cleaned candidate SQL.

        Args:
            question: Natural language question.
            rules: Applicable OKF concepts.
            revision_feedback: Diagnostic feedback if this is a revision cycle.
            context: Context parameters.
            attempt: Attempt counter for tracking revisions.

        Returns:
            GenerationResult containing extracted SQL, prompt, and model metadata.
        """
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
        """Extracts and cleans SQL query from markdown code fences or raw LLM output.

        Args:
            raw_text: Model output text potentially containing markdown code fences.

        Returns:
            Cleaned SQL query terminating with a single semicolon.
        """
        if not raw_text or not raw_text.strip():
            return ""

        cleaned = raw_text.strip()

        # 1. Search for standard markdown code block: ```sql ... ``` or ``` ... ```
        m = re.search(r"```(?:sql)?\s*\n?(.*?)\n?```", cleaned, re.DOTALL | re.IGNORECASE)
        in_code_block = False
        if m and m.group(1).strip():
            candidate = m.group(1).strip()
            in_code_block = True
        else:
            # 2. Strip leading/trailing code fence markers if unclosed
            candidate = re.sub(r"^```(?:sql)?\s*", "", cleaned, flags=re.IGNORECASE).strip()
            candidate = re.sub(r"\s*```$", "", candidate).strip()

        # 3. Strip any stray markdown backtick fences from individual lines
        clean_lines = [
            line for line in candidate.splitlines()
            if not line.strip().startswith("```") and line.strip() != "```"
        ]
        candidate = "\n".join(clean_lines).strip()

        # 4. Only strip conversational preamble if not in code block and preamble has no statements/mutations
        if not in_code_block:
            sql_match = re.search(r"\b(SELECT|WITH)\b.*", candidate, re.DOTALL | re.IGNORECASE)
            if sql_match:
                preamble = candidate[:sql_match.start()].strip()
                mutating_words = {"DROP", "DELETE", "INSERT", "UPDATE", "CREATE", "ALTER", "PRAGMA", "ATTACH", "DETACH", "TRUNCATE"}
                words = set(re.findall(r"\b[A-Za-z]+\b", preamble.upper()))
                if ";" not in preamble and not (words & mutating_words):
                    candidate = sql_match.group(0).strip()

        # 5. Clean residual backtick fragments or literal ```sql markers
        candidate = re.sub(r"```(?:sql)?", "", candidate, flags=re.IGNORECASE).strip()

        if not candidate or not candidate.rstrip(";").strip():
            return ""

        return candidate.rstrip(";") + ";"
