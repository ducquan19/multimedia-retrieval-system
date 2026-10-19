import logging
import threading
from pathlib import Path

import torch
from PIL import Image
from transformers import Blip2ForImageTextRetrieval, Blip2Processor

from models.candidate import ScoredCandidate

logger = logging.getLogger(__name__)


class BLIP2Reranker:
    """Rerank candidates with the BLIP-2 image-text matching (ITM) head.

    Scores are match probabilities in [0, 1], so they can be multiplied with other scores.
    Only the first ``depth`` candidates are rescored (images are batched); the rest keep their
    order below them, because scoring hundreds of images per query is too slow to be useful.
    """

    def __init__(
        self,
        data_root: Path,
        enable: bool = False,
        model_id: str = "Salesforce/blip2-itm-vit-g",
        device: str | None = None,
        depth: int = 100,
        batch_size: int = 16,
        revision: str | None = None,
    ) -> None:
        self.data_root = data_root
        self.enable = enable
        self.depth = depth
        self.batch_size = batch_size
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self._dtype = torch.float16 if self.device.startswith("cuda") else torch.float32
        self._lock = threading.Lock()
        self.processor = None
        self.model = None

        if self.enable:
            logger.debug("Initializing BLIP-2 reranker %s on %s...", model_id, self.device)
            try:
                self.processor = Blip2Processor.from_pretrained(model_id, revision=revision)
                self.model = (
                    Blip2ForImageTextRetrieval.from_pretrained(
                        model_id, revision=revision, dtype=self._dtype
                    )
                    .to(self.device)
                    .eval()
                )
                logger.info("BLIP-2 reranker %s loaded on %s", model_id, self.device)
            except Exception:  # noqa: BLE001 - reranking is optional
                logger.exception("Failed to load BLIP-2 model; reranking is disabled")
                self.enable = False

    @property
    def ready(self) -> bool:
        return self.enable and self.model is not None and self.processor is not None

    def match_probabilities(self, query: str, image_paths: list[str]) -> list[float]:
        """ITM match probability of every image with the query; 0.0 for unreadable images."""
        probabilities: list[float] = []
        for start in range(0, len(image_paths), self.batch_size):
            probabilities.extend(
                self._score_batch(query, image_paths[start : start + self.batch_size])
            )
        return probabilities

    def _score_batch(self, query: str, image_paths: list[str]) -> list[float]:
        images: list[Image.Image] = []
        readable: list[int] = []
        for position, image_path in enumerate(image_paths):
            try:
                with Image.open(self.data_root / image_path) as image:
                    images.append(image.convert("RGB"))
                readable.append(position)
            except OSError as exc:
                logger.warning("Failed to read image %s: %s", image_path, exc)
        scores = [0.0] * len(image_paths)
        if not images:
            return scores

        inputs = self.processor(
            images=images, text=[query] * len(images), padding=True, return_tensors="pt"
        ).to(self.device)
        inputs["pixel_values"] = inputs["pixel_values"].to(self._dtype)
        with self._lock, torch.inference_mode():
            logits = self.model(**inputs, use_image_text_matching_head=True).logits_per_image
            matches = torch.softmax(logits.float(), dim=1)[:, 1].tolist()
        for position, probability in zip(readable, matches, strict=True):
            scores[position] = probability
        return scores

    def rerank(self, query: str, candidates: list[ScoredCandidate]) -> list[ScoredCandidate]:
        """Candidates with the head rescored by ITM probability and sorted by it."""
        if not self.ready or not candidates:
            return candidates

        head, tail = candidates[: self.depth], candidates[self.depth :]
        logger.info("Reranking %d candidates with BLIP-2", len(head))
        probabilities = self.match_probabilities(query, [c.image_path for c in head])
        reranked = sorted(
            (c.with_score(p) for c, p in zip(head, probabilities, strict=True)),
            key=lambda c: c.similarity_score,
            reverse=True,
        )
        # The tail keeps its order below the head; its fused scores are not comparable to ITM.
        return reranked + [c.with_score(0.0) for c in tail]
