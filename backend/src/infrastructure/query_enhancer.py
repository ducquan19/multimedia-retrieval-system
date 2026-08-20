import logging
from typing import Protocol
from pydantic import BaseModel, Field

try:
    from google import genai
except ImportError:
    genai = None

from schemas.search import QueryVariants, QueryVariantsBatch
from pathlib import Path

logger = logging.getLogger(__name__)

_GEMINI_MODEL = "gemini-3.5-flash-lite"


class QueryEnhancer(Protocol):
    def enhance(self, query: str, query_type: str) -> QueryVariants | None: ...
    def enhance_batch(self, queries: dict[int, str]) -> dict[int, QueryVariants] | None: ...


class GeminiQueryEnhancer:
    """Uses Google Gemini to generate 1 English query variation and predict search weights."""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key
        if genai:
            self.client = genai.Client(api_key=api_key) if api_key else genai.Client()
        else:
            self.client = None

    def enhance(self, query: str, query_type: str) -> QueryVariants | None:
        if not self.client:
            logger.warning("google-genai is not installed or client failed to initialize. Falling back.")
            return None

        if query_type == "VQA":
            prompt = f"""
            The user has provided a question about a video in Vietnamese: "{query}".
            Your task is to convert this question into a declarative visual search query (in English) that describes what a frame containing the answer would look like.
            Do not answer the question. Only describe the concrete visual elements (objects, actions, settings) required to find the answer.
            Set w_vis to 1.0, w_ocr to 0.0, and w_asr to 0.0.
            """
        else:
            prompt = f"""
            You are an expert prompt engineer for multimodal contrastive vision-language models.
            The user has provided a search query in Vietnamese: "{query}".

            Your task:
            1. Translate and expand this query into exactly 1 highly descriptive English variation focusing on visual elements.
            2. Analyze the semantic intent of the query and predict weights (0.0 to 1.0) for the 3 search modalities:
               - w_vis: Visual search weight (high if looking for objects, colors, actions, scenes).
               - w_ocr: OCR text search weight (high if explicitly looking for text, banners, signs, or subtitles written on screen).
               - w_asr: ASR speech search weight (high if looking for spoken dialog, news reports, conversations, or phrases).
            """

        try:
            response = self.client.models.generate_content(
                model=_GEMINI_MODEL,
                contents=prompt,
                config=genai.types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=QueryVariants,
                ),
            )

            # The structured output should match our Pydantic schema
            if response.parsed:
                variants = response.parsed.variants
                if len(variants) == 1:
                    logger.info(f"Gemini enhanced queries for '{query}':\n" + "\n".join(f"- {v}" for v in variants))
                    logger.info(f"Predicted weights: w_vis={response.parsed.w_vis}, w_ocr={response.parsed.w_ocr}, w_asr={response.parsed.w_asr}")
                    return response.parsed

            logger.warning("Gemini did not return exactly 1 variants. Falling back.")
            return None

        except Exception as e:
            logger.warning(f"Failed to enhance query with Gemini: {e}")
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
        1. Translate and expand it into exactly 1 highly descriptive English variation focusing on visual elements.
        2. Analyze the semantic intent and predict weights (0.0 to 1.0) for the 3 search modalities (w_vis, w_ocr, w_asr).

        Return a list of results, where each result contains the event_index and its corresponding QueryVariants.
        """

        try:
            response = self.client.models.generate_content(
                model=_GEMINI_MODEL,
                contents=prompt,
                config=genai.types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=QueryVariantsBatch,
                ),
            )

            if response.parsed:
                results_list = response.parsed.results
                results_dict = {item.event_index: item.result for item in results_list}
                logger.info(f"Gemini enhanced batch queries successfully. Received {len(results_dict)} items.")
                return results_dict

            logger.warning("Gemini did not return valid batch variants. Falling back.")
            return None

        except Exception as e:
            logger.warning(f"Failed to enhance batch query with Gemini: {e}")
            return None
