import logging
from typing import Literal, Protocol

from pydantic import BaseModel, Field

try:
    from google import genai
except ImportError:
    genai = None

from schemas.search import KISQueryPlan, QueryVariants, QueryVariantsBatch

logger = logging.getLogger(__name__)

_GEMINI_MODEL = "gemini-3.5-flash-lite"
_KIS_PLAN_CACHE_SIZE = 128


class _GeminiKISQueryPlanEvent(BaseModel):
    """Gemini-compatible structured-output event."""

    event_index: int = Field(ge=1)
    source_span_vi: str
    visual_query_en: str | None = None
    asr_query_vi: str | None = None
    importance: Literal["anchor", "supporting", "context"] = "supporting"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    inferred: bool = False


class _GeminiKISQueryPlan(BaseModel):
    """Permissive transport schema; the public schema validates the final plan."""

    search_mode: Literal["single_anchor", "multi_anchor", "temporal_sequence"]
    events: list[_GeminiKISQueryPlanEvent] = Field(min_length=1, max_length=10)
    warnings: list[str] = Field(default_factory=list)


class QueryEnhancer(Protocol):
    def enhance(self, query: str, query_type: str) -> QueryVariants | None: ...
    def enhance_batch(self, queries: dict[int, str]) -> dict[int, QueryVariants] | None: ...
    def plan_kis(self, query: str) -> KISQueryPlan | None: ...


class GeminiQueryEnhancer:
    """Uses Google Gemini to generate 1 English query variation and predict search weights."""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key
        self._kis_plan_cache: dict[str, KISQueryPlan] = {}
        if genai:
            self.client = genai.Client(api_key=api_key) if api_key else genai.Client()
        else:
            self.client = None

    def enhance(self, query: str, query_type: str) -> QueryVariants | None:
        if not self.client:
            logger.warning(
                "google-genai is not installed or client failed to initialize. Falling back."
            )
            return None

        if query_type == "VQA":
            prompt = f"""
            The user has provided a question about a video in Vietnamese: "{query}".
            Your task is to convert this question into a concise, declarative visual search query (in English) that describes what a frame containing the answer would look like.
            
            STRICT RULES:
            - Do not answer the question. Only describe the concrete visual elements (objects, actions, settings) required to find the answer.
            - Do NOT hallucinate, guess, or add any redundant facts not implied by the question.
            - Keep it short, objective, and highly relevant to contrastive vision-language models.
            - Set w_vis to 1.0 and w_asr to 0.0.
            """
        else:
            prompt = f"""
            You are an expert prompt engineer for multimodal contrastive vision-language models (like CLIP, SigLIP, BEiT-3).
            The user has provided a search query in Vietnamese: "{query}".

            Your task:
            1. Translate this query into exactly 1 highly descriptive English variation focusing on visual elements.
            
            STRICT RULES FOR TRANSLATION:
            - Ensure the translation is concise, accurate, and captures the exact meaning.
            - Do NOT hallucinate, make up details, or add redundant descriptions that were not in the original query.
            - Focus purely on objective visual concepts (nouns, verbs, attributes). Avoid flowery or abstract language.
            
            2. Analyze the semantic intent of the query and predict weights (0.0 to 1.0) for the 2 search modalities:
               - w_vis: Visual search weight (high if looking for objects, colors, actions, scenes).
               - w_asr: ASR speech search weight (high if looking for spoken dialog, news reports, conversations, or phrases).
            """

        try:
            response = self.client.models.generate_content(
                model=_GEMINI_MODEL,
                contents=prompt,
                config=genai.types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=QueryVariants,
                    temperature=0.2,
                    automatic_function_calling=genai.types.AutomaticFunctionCallingConfig(
                        disable=True
                    ),
                ),
            )

            # The structured output should match our Pydantic schema
            if response.parsed:
                variants = response.parsed.variants
                if len(variants) == 1:
                    logger.info(
                        f"Gemini enhanced queries for '{query}':\n"
                        + "\n".join(f"- {v}" for v in variants)
                    )
                    logger.info(
                        f"Predicted weights: w_vis={response.parsed.w_vis}, w_asr={response.parsed.w_asr}"
                    )
                    return response.parsed

            logger.warning("Gemini did not return exactly 1 variants. Falling back.")
            return None

        except Exception as e:
            logger.warning(f"Failed to enhance query with Gemini: {e}")
            return None

    def plan_kis(self, query: str) -> KISQueryPlan | None:
        """Turn a raw Vietnamese KIS description into an editable multimodal plan."""
        if not self.client:
            logger.warning("Gemini is unavailable; cannot create a KIS query plan.")
            return None

        cache_key = " ".join(query.split())
        cached_plan = self._kis_plan_cache.get(cache_key)
        if cached_plan is not None:
            logger.info("Reusing cached KIS query plan without calling Gemini.")
            return cached_plan

        prompt = f"""
        You plan retrieval for a Vietnamese Known Item Search (KIS) video query.
        Convert the raw query below into a small, evidence-grounded search plan.

        RAW QUERY:
        {query}

        RULES:
        - This is KIS only. Do not answer a VQA question and do not create a TRAKE request.
        - Split only when the text describes genuinely different visible moments over time.
        - source_span_vi must be copied from or closely preserve evidence in the raw query.
        - visual_query_en must describe only concrete content that could be visible in one frame.
        - Put spoken content in asr_query_vi, in Vietnamese. Do not mix the full narrative into it.
        - Omit pure background topics, editorial framing, and non-observable facts. Use context
          only for low-priority evidence that is still searchable in visual or ASR data.
        - Use inferred=true for world-knowledge deductions not literally stated, and add a warning.
        - Select at least one visually distinctive or textually distinctive event as anchor.
        - Prefer 1-4 events. Never invent people, objects, actions, speech, text, or ordering.
        - search_mode is single_anchor for one decisive frame, multi_anchor for unordered evidence,
          or temporal_sequence only when ordering is explicit (for example first/then/finally).
        - confidence is confidence that the event faithfully represents the raw query, not a
          retrieval score.
        """

        try:
            response = self.client.models.generate_content(
                model=_GEMINI_MODEL,
                contents=prompt,
                config=genai.types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=_GeminiKISQueryPlan,
                    temperature=0.1,
                    max_output_tokens=1200,
                    automatic_function_calling=genai.types.AutomaticFunctionCallingConfig(
                        disable=True
                    ),
                ),
            )
            if response.parsed:
                plan = KISQueryPlan.model_validate(response.parsed.model_dump())
                if len(self._kis_plan_cache) >= _KIS_PLAN_CACHE_SIZE:
                    oldest_key = next(iter(self._kis_plan_cache))
                    del self._kis_plan_cache[oldest_key]
                self._kis_plan_cache[cache_key] = plan
                logger.info(
                    "Gemini planned KIS query with %d event(s).", len(plan.events)
                )
                return plan
            logger.warning("Gemini did not return a valid KIS query plan.")
        except Exception as exc:
            logger.warning("Failed to plan KIS query with Gemini: %s", exc)
        return None

    def enhance_batch(self, queries: dict[int, str]) -> dict[int, QueryVariants] | None:
        if not self.client or not queries:
            return None

        # Build prompt for all queries
        query_list_str = "\n".join(f"Event {idx}: {q}" for idx, q in queries.items())

        prompt = f"""
        You are an expert prompt engineer for multimodal contrastive vision-language models.
        The user has provided multiple search queries in Vietnamese (for a temporal event search task).

        Queries:
        {query_list_str}

        Your task for EACH query:
        1. Translate it into exactly 1 highly descriptive English variation focusing on visual elements.
        
        STRICT RULES FOR TRANSLATION:
        - Ensure the translation is concise, accurate, and captures the exact meaning.
        - Do NOT hallucinate, make up details, or add redundant descriptions that were not in the original query.
        - Focus purely on objective visual concepts (nouns, verbs, attributes). Avoid flowery or abstract language.
        
        2. Analyze the semantic intent and predict weights (0.0 to 1.0) for the 2 search modalities (w_vis, w_asr).
           - w_vis: high if looking for objects, colors, actions.
           - w_asr: high if looking for spoken dialog, news reports.

        Return a list of results, where each result contains the event_index and its corresponding QueryVariants.
        """

        try:
            response = self.client.models.generate_content(
                model=_GEMINI_MODEL,
                contents=prompt,
                config=genai.types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=QueryVariantsBatch,
                    automatic_function_calling=genai.types.AutomaticFunctionCallingConfig(
                        disable=True
                    ),
                ),
            )

            if response.parsed:
                results_list = response.parsed.results
                results_dict = {item.event_index: item.result for item in results_list}
                logger.info(
                    f"Gemini enhanced batch queries successfully. Received {len(results_dict)} items."
                )
                return results_dict

            logger.warning("Gemini did not return valid batch variants. Falling back.")
            return None

        except Exception as e:
            logger.warning(f"Failed to enhance batch query with Gemini: {e}")
            return None
