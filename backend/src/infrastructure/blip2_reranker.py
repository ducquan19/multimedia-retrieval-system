import logging
from pathlib import Path
from typing import Any

import torch
from PIL import Image
from transformers import Blip2ForImageTextRetrieval, Blip2Processor

logger = logging.getLogger(__name__)


class BLIP2Reranker:
    def __init__(self, data_root: Path, enable: bool = False):
        self.data_root = data_root
        self.enable = enable
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.processor = None
        self.model = None

        if self.enable:
            logger.info("Initializing BLIP-2 Reranker on %s...", self.device)
            try:
                # Using a smaller model for prototype if needed, but keeping the standard ITM one.
                # In production, use "Salesforce/blip2-itm-vit-g"
                model_id = "Salesforce/blip2-itm-vit-g"
                self.processor = Blip2Processor.from_pretrained(model_id)
                self.model = Blip2ForImageTextRetrieval.from_pretrained(
                    model_id, dtype=torch.float16 if self.device == "cuda" else torch.float32
                )
                self.model.to(self.device)
                self.model.eval()
                logger.info("BLIP-2 model loaded successfully!")
            except Exception as e:
                logger.error("Failed to load BLIP-2 model: %s", e)
                self.enable = False

    def rerank(self, query: str, candidates: list['ScoredCandidate']) -> list['ScoredCandidate']:
        """
        Reranks a list of ScoredCandidate using BLIP-2 Image-Text Matching (ITM).
        Returns the sorted list of candidates.
        """
        if not self.enable or not self.model or not self.processor:
            return candidates

        logger.info("Reranking %d candidates with BLIP-2", len(candidates))

        scored_candidates = []
        for candidate in candidates:
            image_path_str = candidate.image_path
            if not image_path_str:
                scored_candidates.append((candidate, 0.0))
                continue

            # Strip leading '/' if present
            if image_path_str.startswith('/'):
                image_path_str = image_path_str[1:]

            full_path = self.data_root / image_path_str

            try:
                raw_image = Image.open(full_path).convert("RGB")
                inputs = self.processor(images=raw_image, text=query, return_tensors="pt").to(
                    self.device,
                    torch.float16 if self.device == "cuda" else torch.float32
                )

                with torch.no_grad():
                    outputs = self.model(**inputs)
                    # BLIP-2 returns contrastive logits in logits_per_image (shape [1, 1])
                    match_prob = outputs.logits_per_image.item()

                scored_candidates.append((candidate, match_prob))
            except Exception as e:
                logger.warning("Failed to score image %s: %s", full_path, e)
                scored_candidates.append((candidate, 0.0))

        # Sort candidates descending by match probability
        scored_candidates.sort(key=lambda x: x[1], reverse=True)

        # Return the candidate objects updated with the new reranked score
        return [c[0].model_copy(update={"similarity_score": c[1]}) for c in scored_candidates]
