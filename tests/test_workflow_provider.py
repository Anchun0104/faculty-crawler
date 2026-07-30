from __future__ import annotations

import json
import unittest

from faculty_workflow.models import CandidateExtraction
from faculty_workflow.providers import (
    DEEPSEEK_TOKEN_PRICES_PER_MILLION,
    DeepSeekProvider,
    InvalidStructuredOutputError,
    MissingAPIKeyError,
    ProviderError,
    ProviderResult,
    _parse_chat_completion_json,
    extraction_from_result,
    policy_from_result,
)


class DeepSeekProviderTests(unittest.TestCase):
    def test_uses_chat_completions_json_output_and_parses_response(self) -> None:
        captured = []
        data = {
            "name": "Ada Lovelace", "email": "ada@example.edu", "last_name": "Lovelace",
            "title_raw": "Professor", "normalized_title": "Professor", "department": "Physics",
            "homepage": "https://example.edu/ada", "professional_relevance": "relevant",
            "email_ownership": "verified", "homepage_identity": "verified", "official_source": True,
            "group_homepage": False, "evidence": [], "failure_reasons": [],
        }

        def transport(payload):
            captured.append(payload)
            return {
                "id": "chatcmpl_1", "model": "deepseek-v4-flash",
                "usage": {"prompt_tokens": 100, "completion_tokens": 50, "prompt_cache_hit_tokens": 20},
                "choices": [{"message": {"content": json.dumps(data)}}],
            }

        provider = DeepSeekProvider(api_key="test-key", transport=transport, retries=0)
        policy = policy_from_result(ProviderResult(
            data={
                "discipline": "Physics", "include_topics": ["physics"], "exclude_topics": [],
                "allowed_titles": ["Professor"],
                "title_mappings": [{"raw_title": "Prof.", "normalized_title": "Professor"}],
                "prompt_version": "v1",
            },
            model="deepseek-v4-pro", response_id="", input_tokens=0, output_tokens=0,
            tool_calls=0, estimated_cost_usd=0,
        ))
        result = provider.extract_profile(
            school="Example University", policy=policy, profile_url="https://example.edu/ada",
            page_title="Ada", page_text="Ada Lovelace is Professor of Physics. Email ada@example.edu",
            seed={}, model="deepseek-v4-flash",
        )

        self.assertEqual(extraction_from_result(result).name, "Ada Lovelace")
        self.assertEqual(captured[0]["response_format"], {"type": "json_object"})
        self.assertEqual(captured[0]["thinking"], {"type": "disabled"})
        self.assertEqual(captured[0]["messages"][1]["role"], "user")
        self.assertIn("JSON schema", captured[0]["messages"][0]["content"])
        cache_hit, cache_miss, output = DEEPSEEK_TOKEN_PRICES_PER_MILLION["deepseek-v4-flash"]
        self.assertAlmostEqual(result.estimated_cost_usd, (20 * cache_hit + 80 * cache_miss + 50 * output) / 1_000_000)

    def test_missing_key_and_invalid_json_fail_closed(self) -> None:
        provider = DeepSeekProvider(api_key="", transport=lambda payload: {})
        with self.assertRaises(MissingAPIKeyError):
            provider.generate_policy("Physics", "deepseek-v4-pro")
        with self.assertRaisesRegex(ValueError, "Unexpected extraction fields"):
            CandidateExtraction.from_mapping({"name": "Ada", "invented": "bad"})
        with self.assertRaisesRegex(ValueError, "Missing extraction fields"):
            CandidateExtraction.from_mapping({"name": "Ada"})
        with self.assertRaises(InvalidStructuredOutputError):
            _parse_chat_completion_json({"choices": [{"message": {"content": ""}}]})

    def test_source_discovery_requires_a_directory_url(self) -> None:
        provider = DeepSeekProvider(api_key="test-key", transport=lambda payload: {})
        with self.assertRaises(ProviderError):
            provider.discover_sources("Example University", policy_from_result(ProviderResult(
                data={"discipline": "Physics", "include_topics": ["physics"], "exclude_topics": [], "allowed_titles": ["Professor"], "title_mappings": [], "prompt_version": "v1"},
                model="deepseek-v4-pro", response_id="", input_tokens=0, output_tokens=0,
                tool_calls=0, estimated_cost_usd=0,
            )), "deepseek-v4-flash")


if __name__ == "__main__":
    unittest.main()
