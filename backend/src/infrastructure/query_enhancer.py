import logging
import threading
from collections import OrderedDict
from collections.abc import Sequence
from typing import Literal, Protocol

from pydantic import BaseModel, Field

try:
    from google import genai
except ImportError:
    genai = None

from schemas.search import KISQueryPlan, ObjectQueryTerm, QueryVariants, SearchSources

logger = logging.getLogger(__name__)

DEFAULT_GEMINI_MODEL = "gemini-3.5-flash-lite"
_KIS_PLAN_CACHE_SIZE = 128
_ENHANCE_CACHE_SIZE = 256
_MAX_AUTO_OBJECTS = 4


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


class _GeminiObjectTerm(BaseModel):
    label: str
    min_count: int = 1


class _GeminiQueryVariants(BaseModel):
    """Gemini-compatible transport schema for one enhanced query."""

    variants: list[str] = Field(min_length=1, max_length=1)
    asr_query_vi: str | None = None
    objects: list[_GeminiObjectTerm] = Field(default_factory=list)
    w_vis: float = 1.0
    w_asr: float = 0.0
    w_obj: float = 0.0


class _GeminiBatchItem(BaseModel):
    event_index: int
    result: _GeminiQueryVariants


class _GeminiQueryVariantsBatch(BaseModel):
    results: list[_GeminiBatchItem]


_MODALITY_GUIDE = """
The retrieval system fuses three modalities over video keyframes:
- visual: SigLIP / BEiT-3 text-to-image embedding search, queried in English.
- asr: BM25 keyword search over Vietnamese speech transcripts of each shot.
- object: an Open Images object detector run on every keyframe (class name + instance count).
"""

_OUTPUT_RULES = """
Produce:
1. variants: exactly 1 concise English description of what the target frame looks like.
   Keep only objective visual concepts (objects, people, actions, colors, setting, on-screen
   text). Never add details that are not in the query.
2. asr_query_vi: short Vietnamese keywords or phrases that are likely to be SPOKEN in that
   moment (quoted speech, names, topics, numbers). Use null when nothing would be spoken.
3. objects: 0-{max_objects} detector classes that must be visible in the target frame.
   - Only objects the query explicitly names (or an exact synonym). Do not infer objects
     from roles or situations (e.g. "reporter" does not imply Microphone).
   - Copy class names EXACTLY from the allowed class list below; never invent a class.
   - min_count is the number of instances explicitly stated in the query (default 1).
   - Prefer distinctive classes. Skip ubiquitous classes (Person, Man, Woman, Clothing,
     Human face, Tree, Building) unless the query states how many of them there are.
4. Weights from 0.0 to 1.0 describing how useful each modality is for THIS query:
   - w_vis: high for scenes, actions, appearances and layouts.
   - w_asr: high when the query quotes or paraphrases speech, a news topic or spoken names.
   - w_obj: high when the query names distinctive or counted objects; 0.0 if objects is empty.
{enabled_note}
Allowed detector classes:
{labels}
"""


class _LruCache[T]:
    """Small thread-safe LRU cache (requests run concurrently in the threadpool)."""

    def __init__(self, max_size: int) -> None:
        self._max_size = max_size
        self._items: OrderedDict[str, T] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> T | None:
        with self._lock:
            value = self._items.get(key)
            if value is not None:
                self._items.move_to_end(key)
            return value

    def put(self, key: str, value: T) -> None:
        with self._lock:
            self._items[key] = value
            self._items.move_to_end(key)
            while len(self._items) > self._max_size:
                self._items.popitem(last=False)


class QueryEnhancer(Protocol):
    def enhance(
        self, query: str, query_type: str, sources: SearchSources | None = None
    ) -> QueryVariants | None: ...
    def enhance_batch(
        self, queries: dict[int, str], sources: SearchSources | None = None
    ) -> dict[int, QueryVariants] | None: ...
    def plan_kis(self, query: str) -> KISQueryPlan | None: ...


class GeminiQueryEnhancer:
    """Uses Gemini to rewrite a query, pick detector objects and weight each modality."""

    def __init__(
        self,
        api_key: str | None = None,
        object_labels: Sequence[str] = (),
        model: str = DEFAULT_GEMINI_MODEL,
    ) -> None:
        self.model = model
        self._kis_plan_cache: _LruCache[KISQueryPlan] = _LruCache(_KIS_PLAN_CACHE_SIZE)
        self._enhance_cache: _LruCache[QueryVariants] = _LruCache(_ENHANCE_CACHE_SIZE)
        self._object_labels = tuple(object_labels)
        self._label_lookup = {label.casefold(): label for label in self._object_labels}
        self.client = None
        if genai is None:
            logger.warning("google-genai is not installed; Enhance query is disabled.")
        elif not api_key:
            logger.warning("AIC_GEMINI_API_KEY is not set; Enhance query is disabled.")
        else:
            try:
                self.client = genai.Client(api_key=api_key)
            except Exception:  # noqa: BLE001 - enhancement is optional
                logger.exception("Could not create the Gemini client; Enhance query is disabled.")

    @property
    def available(self) -> bool:
        return self.client is not None

    def enhance(
        self, query: str, query_type: str, sources: SearchSources | None = None
    ) -> QueryVariants | None:
        if not self.client:
            return None

        cache_key = f"{query_type}|{self._sources_key(sources)}|{' '.join(query.split())}"
        cached = self._enhance_cache.get(cache_key)
        if cached is not None:
            logger.info("Reusing cached enhanced query without calling Gemini.")
            return cached

        if query_type == "VQA":
            task = f"""
            The user asks a question about a video in Vietnamese: "{query}".
            Describe the frame that contains the answer; do NOT answer the question.
            Visual evidence usually dominates, but use ASR when the answer is spoken.
            """
        elif query_type == "TRAFFIC":
            task = f"""
            The user describes one moment seen by a fixed traffic surveillance camera in
            Ho Chi Minh City, in Vietnamese: "{query}".
            Street names, dates, clock times, time of day and weather are applied as metadata
            filters, so leave them out of the visual description. Describe the vehicles, people,
            colors, positions in the frame and actions. There is no speech: asr_query_vi is null.
            """
        else:
            task = f"""
            The user describes one moment of a video in Vietnamese: "{query}".
            """

        prompt = f"""
        You are a query planner for a hybrid video retrieval system.
        {_MODALITY_GUIDE}
        {task}
        {self._output_rules(sources)}
        """

        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=genai.types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=_GeminiQueryVariants,
                    temperature=0.2,
                    automatic_function_calling=genai.types.AutomaticFunctionCallingConfig(
                        disable=True
                    ),
                ),
            )
            if response.parsed:
                enhanced = self._to_query_variants(response.parsed)
                if enhanced is not None:
                    logger.info(
                        "Gemini enhanced '%s' -> %s | asr=%s | objects=%s | "
                        "w_vis=%.2f w_asr=%.2f w_obj=%.2f",
                        query,
                        enhanced.variants[0],
                        enhanced.asr_query_vi,
                        [f"{o.label}>={o.min_count}" for o in enhanced.objects],
                        enhanced.w_vis,
                        enhanced.w_asr,
                        enhanced.w_obj,
                    )
                    self._enhance_cache.put(cache_key, enhanced)
                    return enhanced

            logger.warning("Gemini did not return exactly 1 variant. Falling back.")
            return None

        except Exception as exc:  # noqa: BLE001 - any Gemini failure falls back to the raw query
            logger.warning("Failed to enhance query with Gemini: %s", exc)
            return None

    def enhance_batch(
        self, queries: dict[int, str], sources: SearchSources | None = None
    ) -> dict[int, QueryVariants] | None:
        if not self.client or not queries:
            return None

        query_list_str = "\n".join(f"Event {idx}: {q}" for idx, q in queries.items())
        prompt = f"""
        You are a query planner for a hybrid video retrieval system.
        {_MODALITY_GUIDE}
        The user describes several consecutive events of one video in Vietnamese
        (a temporal event search). Treat every event independently.

        Events:
        {query_list_str}

        For EACH event:
        {self._output_rules(sources)}

        Return one result per event with its event_index.
        """

        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=genai.types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=_GeminiQueryVariantsBatch,
                    temperature=0.2,
                    automatic_function_calling=genai.types.AutomaticFunctionCallingConfig(
                        disable=True
                    ),
                ),
            )

            if response.parsed:
                results_dict = {}
                for item in response.parsed.results:
                    enhanced = self._to_query_variants(item.result)
                    if item.event_index in queries and enhanced is not None:
                        results_dict[item.event_index] = enhanced
                if results_dict:
                    logger.info(
                        "Gemini enhanced batch queries successfully. Received %d items.",
                        len(results_dict),
                    )
                    return results_dict

            logger.warning("Gemini did not return valid batch variants. Falling back.")
            return None

        except Exception as exc:  # noqa: BLE001 - any Gemini failure falls back to the raw queries
            logger.warning("Failed to enhance batch query with Gemini: %s", exc)
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
                model=self.model,
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
                plan = KISQueryPlan.model_validate(
                    {**response.parsed.model_dump(), "planner_model": self.model}
                )
                self._kis_plan_cache.put(cache_key, plan)
                logger.info("Gemini planned KIS query with %d event(s).", len(plan.events))
                return plan
            logger.warning("Gemini did not return a valid KIS query plan.")
        except Exception as exc:  # noqa: BLE001 - reported to the user as a planning failure
            logger.warning("Failed to plan KIS query with Gemini: %s", exc)
        return None

    def _output_rules(self, sources: SearchSources | None) -> str:
        enabled_note = ""
        if sources is not None:
            enabled = [
                name
                for name, on in (
                    ("visual", sources.image),
                    ("asr", sources.asr),
                    ("object", sources.object),
                )
                if on
            ]
            enabled_note = (
                f"Only these modalities are enabled: {', '.join(enabled)}. "
                "Still fill every field; disabled modalities are ignored downstream."
            )
        labels = ", ".join(self._object_labels) if self._object_labels else "(none: return [])"
        return _OUTPUT_RULES.format(
            max_objects=_MAX_AUTO_OBJECTS, enabled_note=enabled_note, labels=labels
        )

    def _to_query_variants(self, parsed: _GeminiQueryVariants) -> QueryVariants | None:
        """Validate Gemini output: exact detector labels, bounded counts and weights."""
        if len(parsed.variants) != 1 or not parsed.variants[0].strip():
            return None

        objects: list[ObjectQueryTerm] = []
        seen: set[str] = set()
        for term in parsed.objects:
            label = self._label_lookup.get(term.label.strip().casefold())
            if label is None:
                if term.label.strip():
                    logger.info("Dropping unknown Gemini object label: %s", term.label)
                continue
            if label in seen:
                continue
            seen.add(label)
            objects.append(ObjectQueryTerm(label=label, min_count=min(max(term.min_count, 1), 50)))
            if len(objects) >= _MAX_AUTO_OBJECTS:
                break

        def clamp(value: float) -> float:
            return min(max(float(value), 0.0), 1.0)

        w_vis, w_asr = clamp(parsed.w_vis), clamp(parsed.w_asr)
        w_obj = clamp(parsed.w_obj) if objects else 0.0
        if w_vis + w_asr + w_obj == 0:
            w_vis = 1.0
        return QueryVariants(
            variants=[parsed.variants[0].strip()],
            w_vis=w_vis,
            w_asr=w_asr,
            w_obj=w_obj,
            asr_query_vi=(parsed.asr_query_vi or "").strip() or None,
            objects=tuple(objects),
        )

    @staticmethod
    def _sources_key(sources: SearchSources | None) -> str:
        if sources is None:
            return "-"
        return "".join("1" if on else "0" for on in (sources.image, sources.asr, sources.object))
