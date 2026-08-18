import logging
from typing import Protocol
from pydantic import BaseModel, Field

try:
    from google import genai
except ImportError:
    genai = None

logger = logging.getLogger(__name__)

class QueryEnhancer(Protocol):
    def enhance(self, query: str, query_type: str) -> list[str]: ...



class QueryVariants(BaseModel):
    variants: list[str] = Field(
        description="Exactly 1 highly descriptive English variation of the original query.",
        min_length=1,
        max_length=1
    )


class GeminiQueryEnhancer:
    """Uses Google Gemini to generate 1 English query variation for visual retrieval models."""
    
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key
        if genai:
            self.client = genai.Client(api_key=api_key) if api_key else genai.Client()
        else:
            self.client = None

    def enhance(self, query: str, query_type: str) -> list[str]:
        if not self.client:
            logger.warning("google-genai is not installed or client failed to initialize. Falling back.")
            return []

        prompt = f"""
        You are an expert prompt engineer for contrastive vision-language models like CLIP, SigLIP, and BEiT-3.
        The user has provided a search query in Vietnamese: "{query}".
        
        Your task:
        1. Translate and expand this query into exactly 1 highly descriptive English variation.
        2. Focus strictly on concrete visual elements (objects, colors, actions, settings) that would physically appear in an image or video frame.
        3. Do not use abstract concepts. Be as visually explicit as possible.
        """

        try:
            response = self.client.models.generate_content(
                model='gemini-2.5-flash-lite',
                contents=prompt,
                config=genai.types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=QueryVariants,
                    temperature=0.7,
                ),
            )
            
            # The structured output should match our Pydantic schema
            if response.parsed:
                variants = response.parsed.variants
                if len(variants) == 1:
                    logger.info(f"Gemini enhanced queries for '{query}':\n" + "\n".join(f"- {v}" for v in variants))
                    return variants
                
            logger.warning("Gemini did not return exactly 1 variants. Falling back.")
            return []
            
        except Exception as e:
            logger.warning(f"Failed to enhance query with Gemini: {e}")
            return []
