from typing import Protocol


class QueryEnhancer(Protocol):
    def enhance(self, query: str, query_type: str) -> str: ...


class MockQueryEnhancer:
    """Deterministic marker-only enhancer; it never calls Gemini."""

    def enhance(self, query: str, query_type: str) -> str:
        return f"[Mock enhanced {query_type}] {query}"
