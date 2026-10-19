"""The Gemini adapter: timeout, accounting and fallback, with a fake client."""

from types import SimpleNamespace

import pytest

from infrastructure import query_enhancer
from infrastructure.query_enhancer import GeminiQueryEnhancer, _GeminiQueryVariants


class _FakeModels:
    def __init__(self, response=None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.calls = 0

    def generate_content(self, **_kwargs):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.response


def enhancer_with(models: _FakeModels) -> GeminiQueryEnhancer:
    enhancer = GeminiQueryEnhancer(api_key="test", object_labels=["Bicycle"])
    enhancer.client = SimpleNamespace(models=models)
    return enhancer


@pytest.mark.skipif(query_enhancer.genai is None, reason="google-genai is not installed")
def test_client_is_created_with_a_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    created = {}

    def fake_client(**kwargs):
        created.update(kwargs)
        return SimpleNamespace()

    monkeypatch.setattr(query_enhancer.genai, "Client", fake_client)

    GeminiQueryEnhancer(api_key="test", timeout_seconds=7.5)

    assert created["http_options"].timeout == 7500


@pytest.mark.skipif(query_enhancer.genai is None, reason="google-genai is not installed")
def test_calls_and_tokens_are_counted() -> None:
    response = SimpleNamespace(
        parsed=_GeminiQueryVariants(variants=["a red bicycle"]),
        usage_metadata=SimpleNamespace(
            prompt_token_count=120, candidates_token_count=30, total_token_count=150
        ),
    )
    models = _FakeModels(response)
    enhancer = enhancer_with(models)

    first = enhancer.enhance("xe đạp đỏ", "KIS")
    again = enhancer.enhance("xe  đạp đỏ", "KIS")  # cached: no second call

    assert first is not None and first.variants == ["a red bicycle"]
    assert again == first
    assert models.calls == 1
    assert enhancer.usage_summary() == "1 calls (0 failed), 150 tokens"


@pytest.mark.skipif(query_enhancer.genai is None, reason="google-genai is not installed")
def test_timeout_falls_back_to_the_raw_query() -> None:
    enhancer = enhancer_with(_FakeModels(error=TimeoutError("deadline exceeded")))

    assert enhancer.enhance("xe đạp đỏ", "KIS") is None
    assert enhancer.plan_kis("xe đạp đỏ") is None
    assert enhancer.usage_summary() == "2 calls (2 failed), 0 tokens"
