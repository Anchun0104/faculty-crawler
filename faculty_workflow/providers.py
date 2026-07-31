from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from faculty_workflow.models import CandidateExtraction, DisciplinePolicy


OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
DEEPSEEK_CHAT_COMPLETIONS_URL = "https://api.deepseek.com/chat/completions"
MODEL_TOKEN_PRICES_PER_MILLION = {
    "gpt-5.6-luna": (1.00, 6.00),
    "gpt-5.6-terra": (2.50, 15.00),
    "gpt-5.6-sol": (5.00, 30.00),
}
WEB_SEARCH_COST_PER_CALL = 0.01
DEEPSEEK_TOKEN_PRICES_PER_MILLION = {
    # Cache-hit, cache-miss, output. Budget reservations intentionally use cache-miss.
    "deepseek-v4-flash": (0.0028, 0.14, 0.28),
    "deepseek-v4-pro": (0.003625, 0.435, 0.87),
}


class ProviderError(RuntimeError):
    pass


class MissingAPIKeyError(ProviderError):
    pass


class InvalidStructuredOutputError(ProviderError):
    pass


@dataclass(frozen=True)
class ProviderResult:
    data: dict[str, Any]
    model: str
    response_id: str
    input_tokens: int
    output_tokens: int
    tool_calls: int
    estimated_cost_usd: float


class ModelProvider(Protocol):
    def generate_policy(self, discipline: str, model: str) -> ProviderResult: ...

    def discover_sources(
        self,
        school: str,
        policy: DisciplinePolicy,
        model: str,
        *,
        max_results: int = 10,
    ) -> ProviderResult: ...

    def extract_profile(
        self,
        *,
        school: str,
        policy: DisciplinePolicy,
        profile_url: str,
        page_title: str,
        page_text: str,
        seed: dict[str, str],
        model: str,
    ) -> ProviderResult: ...

    def estimate_request_cost(self, model: str, input_characters: int, max_output_tokens: int) -> float: ...


class OpenAIProvider:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        endpoint: str = OPENAI_RESPONSES_URL,
        timeout: int = 120,
        retries: int = 2,
        transport: Any | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.environ.get("OPENAI_API_KEY", "")
        self.endpoint = endpoint
        self.timeout = timeout
        self.retries = retries
        self.transport = transport or self._http_transport

    def generate_policy(self, discipline: str, model: str) -> ProviderResult:
        prompt = f"""Create a reviewable collection policy for the academic discipline: {discipline}.
Return broad candidate-recall topics, explicit exclusions that prevent adjacent-discipline drift,
the four default normalized titles, and common official-title mappings. Do not collect people yet.
The user will review this draft before any crawl starts."""
        return self._call(
            operation="generate_policy",
            model=model,
            prompt=prompt,
            schema_name="discipline_policy",
            schema=_POLICY_SCHEMA,
            max_output_tokens=2000,
        )

    def discover_sources(
        self,
        school: str,
        policy: DisciplinePolicy,
        model: str,
        *,
        max_results: int = 10,
    ) -> ProviderResult:
        prompt = f"""Find official faculty or staff directory entry points for this university and discipline.
University: {school}
Discipline: {policy.discipline}
Include topics: {', '.join(policy.include_topics)}
Exclude topics: {', '.join(policy.exclude_topics) or 'none'}
Use no more than three web searches and return at most {max_results} candidate URLs. Prefer university-owned faculty directories and official
research portals. Do not treat search snippets, aggregators, social media, PDFs, or news articles as
faculty directories. URLs are candidates only; the application will fetch and verify them."""
        return self._call(
            operation="discover_sources",
            model=model,
            prompt=prompt,
            schema_name="source_discovery",
            schema=_DISCOVERY_SCHEMA,
            max_output_tokens=3000,
            tools=[{"type": "web_search"}],
        )

    def extract_profile(
        self,
        *,
        school: str,
        policy: DisciplinePolicy,
        profile_url: str,
        page_title: str,
        page_text: str,
        seed: dict[str, str],
        model: str,
    ) -> ProviderResult:
        prompt = f"""Extract one faculty candidate from the supplied official-page evidence.
Never guess an email, title, department, homepage, identity, or research relevance. Use an empty
string and a failure reason when the page does not state a field. Quotes must be short verbatim
snippets from the supplied text and must use the supplied source URL.

University: {school}
Target discipline: {policy.discipline}
Included topics: {', '.join(policy.include_topics)}
Excluded topics: {', '.join(policy.exclude_topics) or 'none'}
Allowed normalized titles: {', '.join(policy.allowed_titles)}
Title mappings: {json.dumps(policy.title_mappings, ensure_ascii=False)}
Directory seed: {json.dumps(seed, ensure_ascii=False)}
Source URL: {profile_url}
Page title: {page_title}
Page text:
{page_text[:40000]}"""
        return self._call(
            operation="extract_profile",
            model=model,
            prompt=prompt,
            schema_name="faculty_candidate",
            schema=_EXTRACTION_SCHEMA,
            max_output_tokens=4000,
        )

    def estimate_request_cost(self, model: str, input_characters: int, max_output_tokens: int) -> float:
        input_price, output_price = MODEL_TOKEN_PRICES_PER_MILLION.get(model, (5.0, 30.0))
        estimated_input_tokens = max(1, input_characters // 4)
        return (estimated_input_tokens * input_price + max_output_tokens * output_price) / 1_000_000

    def _call(
        self,
        *,
        operation: str,
        model: str,
        prompt: str,
        schema_name: str,
        schema: dict[str, Any],
        max_output_tokens: int,
        tools: list[dict[str, Any]] | None = None,
    ) -> ProviderResult:
        if not self.api_key:
            raise MissingAPIKeyError("OPENAI_API_KEY is not configured")
        payload: dict[str, Any] = {
            "model": model,
            "input": prompt,
            "max_output_tokens": max_output_tokens,
            "reasoning": {"effort": "none" if model.endswith("luna") else "low"},
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "strict": True,
                    "schema": schema,
                }
            },
            "store": False,
            "safety_identifier": _safety_identifier(),
        }
        if tools:
            payload["tools"] = tools

        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                response = self.transport(payload)
                data = _parse_response_json(response)
                usage = response.get("usage") or {}
                input_tokens = int(usage.get("input_tokens") or 0)
                output_tokens = int(usage.get("output_tokens") or 0)
                tool_calls = sum(1 for item in response.get("output") or [] if str(item.get("type", "")).endswith("_call"))
                return ProviderResult(
                    data=data,
                    model=str(response.get("model") or model),
                    response_id=str(response.get("id") or ""),
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    tool_calls=tool_calls,
                    estimated_cost_usd=(
                        _token_cost(model, input_tokens, output_tokens)
                        + tool_calls * WEB_SEARCH_COST_PER_CALL
                    ),
                )
            except (HTTPError, URLError, TimeoutError, ProviderError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt >= self.retries or isinstance(exc, MissingAPIKeyError):
                    break
                time.sleep(2**attempt)
        raise ProviderError(f"OpenAI {operation} failed after {self.retries + 1} attempts: {last_error}")

    def _http_transport(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = Request(
            self.endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "faculty-workflow/1.0",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:1000]
            raise ProviderError(f"OpenAI HTTP {exc.code}: {body}") from exc


class DeepSeekProvider:
    """DeepSeek Chat Completions provider with local structural validation."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        endpoint: str = DEEPSEEK_CHAT_COMPLETIONS_URL,
        timeout: int = 120,
        retries: int = 2,
        transport: Any | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.environ.get("DEEPSEEK_API_KEY", "")
        self.endpoint = endpoint
        self.timeout = timeout
        self.retries = retries
        self.transport = transport or self._http_transport

    def generate_policy(self, discipline: str, model: str) -> ProviderResult:
        prompt = f"""Create a reviewable collection policy for the academic discipline: {discipline}.
Return broad candidate-recall topics, explicit exclusions that prevent adjacent-discipline drift,
the four default normalized titles, and common official-title mappings. Do not collect people yet.
The user will review this draft before any crawl starts."""
        return self._call(
            operation="generate_policy",
            model=model,
            prompt=prompt,
            schema_name="discipline_policy",
            schema=_POLICY_SCHEMA,
            max_output_tokens=2000,
        )

    def discover_sources(
        self,
        school: str,
        policy: DisciplinePolicy,
        model: str,
        *,
        max_results: int = 10,
    ) -> ProviderResult:
        raise ProviderError(
            "DeepSeek source discovery is disabled. Provide an official directory URL in the school table."
        )

    def extract_profile(
        self,
        *,
        school: str,
        policy: DisciplinePolicy,
        profile_url: str,
        page_title: str,
        page_text: str,
        seed: dict[str, str],
        model: str,
    ) -> ProviderResult:
        prompt = f"""Extract one faculty candidate from the supplied official-page evidence.
Never guess an email, title, department, homepage, identity, or research relevance. Use an empty
string and a failure reason when the page does not state a field. Quotes must be short verbatim
snippets from the supplied text and must use the supplied source URL.

University: {school}
Target discipline: {policy.discipline}
Included topics: {', '.join(policy.include_topics)}
Excluded topics: {', '.join(policy.exclude_topics) or 'none'}
Allowed normalized titles: {', '.join(policy.allowed_titles)}
Title mappings: {json.dumps(policy.title_mappings, ensure_ascii=False)}
Directory seed: {json.dumps(seed, ensure_ascii=False)}
Source URL: {profile_url}
Page title: {page_title}
Page text:
{page_text[:40000]}"""
        return self._call(
            operation="extract_profile",
            model=model,
            prompt=prompt,
            schema_name="faculty_candidate",
            schema=_EXTRACTION_SCHEMA,
            max_output_tokens=4000,
        )

    def estimate_request_cost(self, model: str, input_characters: int, max_output_tokens: int) -> float:
        _, input_price, output_price = DEEPSEEK_TOKEN_PRICES_PER_MILLION.get(model, (0.01, 1.0, 2.0))
        estimated_input_tokens = max(1, input_characters // 4)
        return (estimated_input_tokens * input_price + max_output_tokens * output_price) / 1_000_000

    def _call(
        self,
        *,
        operation: str,
        model: str,
        prompt: str,
        schema_name: str,
        schema: dict[str, Any],
        max_output_tokens: int,
    ) -> ProviderResult:
        if not self.api_key:
            raise MissingAPIKeyError("DEEPSEEK_API_KEY is not configured")
        schema_prompt = json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Return one valid JSON object only, without markdown. The object must match "
                        f"this JSON schema exactly: {schema_prompt}"
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0,
            "max_tokens": max_output_tokens,
            "thinking": {"type": "enabled" if model == "deepseek-v4-pro" else "disabled"},
        }
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                response = self.transport(payload)
                data = _parse_chat_completion_json(response)
                usage = response.get("usage") or {}
                input_tokens = int(usage.get("prompt_tokens") or 0)
                output_tokens = int(usage.get("completion_tokens") or 0)
                cached_tokens = int(usage.get("prompt_cache_hit_tokens") or 0)
                return ProviderResult(
                    data=data,
                    model=str(response.get("model") or model),
                    response_id=str(response.get("id") or ""),
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    tool_calls=0,
                    estimated_cost_usd=_deepseek_token_cost(model, input_tokens, output_tokens, cached_tokens),
                )
            except (HTTPError, URLError, TimeoutError, ProviderError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt >= self.retries or isinstance(exc, MissingAPIKeyError):
                    break
                time.sleep(2**attempt)
        raise ProviderError(f"DeepSeek {operation} failed after {self.retries + 1} attempts: {last_error}")

    def _http_transport(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = Request(
            self.endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "faculty-workflow/1.0",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:1000]
            raise ProviderError(f"DeepSeek HTTP {exc.code}: {body}") from exc


class OpenAICompatibleProvider(DeepSeekProvider):
    """Chat Completions JSON provider for endpoints explicitly configured by the user."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        endpoint: str,
        timeout: int = 120,
        retries: int = 2,
        transport: Any | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.environ.get("OPENAI_API_KEY", "")
        self.endpoint = endpoint
        self.timeout = timeout
        self.retries = retries
        self.transport = transport or self._http_transport

    def _call(
        self,
        *,
        operation: str,
        model: str,
        prompt: str,
        schema_name: str,
        schema: dict[str, Any],
        max_output_tokens: int,
    ) -> ProviderResult:
        if not self.api_key:
            raise MissingAPIKeyError("API key is not configured")
        schema_prompt = json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "Return one valid JSON object only, without markdown. The object must match this JSON schema exactly: " + schema_prompt},
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0,
            "max_tokens": max_output_tokens,
        }
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                response = self.transport(payload)
                data = _parse_chat_completion_json(response)
                usage = response.get("usage") or {}
                return ProviderResult(
                    data=data,
                    model=str(response.get("model") or model),
                    response_id=str(response.get("id") or ""),
                    input_tokens=int(usage.get("prompt_tokens") or 0),
                    output_tokens=int(usage.get("completion_tokens") or 0),
                    tool_calls=0,
                    estimated_cost_usd=0.0,
                )
            except (HTTPError, URLError, TimeoutError, ProviderError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt >= self.retries or isinstance(exc, MissingAPIKeyError):
                    break
                time.sleep(2**attempt)
        raise ProviderError(f"Compatible API {operation} failed after {self.retries + 1} attempts: {last_error}")

    def discover_sources(self, school: str, policy: DisciplinePolicy, model: str, *, max_results: int = 10) -> ProviderResult:
        raise ProviderError("Compatible API source discovery is disabled. Provide an official directory URL.")


def policy_from_result(result: ProviderResult) -> DisciplinePolicy:
    data = dict(result.data)
    mappings = data.get("title_mappings")
    if isinstance(mappings, list):
        data["title_mappings"] = {
            str(item.get("raw_title") or ""): str(item.get("normalized_title") or "")
            for item in mappings
            if isinstance(item, dict) and item.get("raw_title") and item.get("normalized_title")
        }
    return DisciplinePolicy.from_json(data)


def extraction_from_result(result: ProviderResult) -> CandidateExtraction:
    return CandidateExtraction.from_mapping(result.data)


def _parse_response_json(response: dict[str, Any]) -> dict[str, Any]:
    for item in response.get("output") or []:
        if item.get("type") != "message":
            continue
        for content in item.get("content") or []:
            if content.get("type") == "refusal":
                raise InvalidStructuredOutputError(str(content.get("refusal") or "Model refused request"))
            if content.get("type") == "output_text":
                text = content.get("text")
                if not isinstance(text, str):
                    break
                parsed = json.loads(text)
                if not isinstance(parsed, dict):
                    raise InvalidStructuredOutputError("Structured output must be a JSON object")
                return parsed
    raise InvalidStructuredOutputError("OpenAI response did not contain structured output text")


def _parse_chat_completion_json(response: dict[str, Any]) -> dict[str, Any]:
    choices = response.get("choices") or []
    if not choices:
        raise InvalidStructuredOutputError("DeepSeek response did not contain a choice")
    message = dict(choices[0].get("message") or {})
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise InvalidStructuredOutputError("DeepSeek JSON output was empty")
    parsed = json.loads(content)
    if not isinstance(parsed, dict):
        raise InvalidStructuredOutputError("DeepSeek JSON output must be an object")
    return parsed


def _token_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    input_price, output_price = MODEL_TOKEN_PRICES_PER_MILLION.get(model, (5.0, 30.0))
    return (input_tokens * input_price + output_tokens * output_price) / 1_000_000


def _deepseek_token_cost(model: str, input_tokens: int, output_tokens: int, cached_tokens: int = 0) -> float:
    cache_hit_price, cache_miss_price, output_price = DEEPSEEK_TOKEN_PRICES_PER_MILLION.get(model, (0.01, 1.0, 2.0))
    cached = min(max(cached_tokens, 0), max(input_tokens, 0))
    uncached = max(input_tokens - cached, 0)
    return (cached * cache_hit_price + uncached * cache_miss_price + output_tokens * output_price) / 1_000_000


def _safety_identifier() -> str:
    source = os.environ.get("FACULTY_WORKFLOW_INSTALLATION_ID") or os.environ.get("USERNAME") or "local-user"
    return hashlib.sha256(source.encode("utf-8", errors="ignore")).hexdigest()[:32]


_POLICY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["discipline", "include_topics", "exclude_topics", "allowed_titles", "title_mappings", "prompt_version"],
    "properties": {
        "discipline": {"type": "string"},
        "include_topics": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "exclude_topics": {"type": "array", "items": {"type": "string"}},
        "allowed_titles": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "title_mappings": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["raw_title", "normalized_title"],
                "properties": {
                    "raw_title": {"type": "string"},
                    "normalized_title": {"type": "string"},
                },
            },
        },
        "prompt_version": {"type": "string"},
    },
}

_DISCOVERY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["official_domain", "domain_evidence_url", "candidates", "failure_reason"],
    "properties": {
        "official_domain": {"type": "string"},
        "domain_evidence_url": {"type": "string"},
        "candidates": {
            "type": "array",
            "maxItems": 10,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["url", "source_type", "reason"],
                "properties": {
                    "url": {"type": "string"},
                    "source_type": {"type": "string", "enum": ["faculty_directory", "staff_directory", "research_portal"]},
                    "reason": {"type": "string"},
                },
            },
        },
        "failure_reason": {"type": "string"},
    },
}

_EVIDENCE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["field", "quote", "source_url", "extraction_method", "status"],
    "properties": {
        "field": {"type": "string"},
        "quote": {"type": "string"},
        "source_url": {"type": "string"},
        "extraction_method": {"type": "string", "enum": ["model", "directory_seed", "deterministic"]},
        "status": {"type": "string", "enum": ["supported", "ambiguous", "missing"]},
    },
}

_EXTRACTION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "name", "email", "last_name", "title_raw", "normalized_title", "department",
        "homepage", "professional_relevance", "email_ownership", "homepage_identity",
        "official_source", "group_homepage", "evidence", "failure_reasons",
    ],
    "properties": {
        "name": {"type": "string"},
        "email": {"type": "string"},
        "last_name": {"type": "string"},
        "title_raw": {"type": "string"},
        "normalized_title": {"type": "string"},
        "department": {"type": "string"},
        "homepage": {"type": "string"},
        "professional_relevance": {"type": "string", "enum": ["relevant", "uncertain", "not_relevant"]},
        "email_ownership": {"type": "string", "enum": ["verified", "uncertain", "not_found"]},
        "homepage_identity": {"type": "string", "enum": ["verified", "uncertain", "mismatch"]},
        "official_source": {"type": "boolean"},
        "group_homepage": {"type": "boolean"},
        "evidence": {"type": "array", "items": _EVIDENCE_SCHEMA},
        "failure_reasons": {"type": "array", "items": {"type": "string"}},
    },
}
