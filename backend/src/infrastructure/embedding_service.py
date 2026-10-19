import logging
import threading
from pathlib import Path

import numpy as np
import sentencepiece as spm
import torch
from transformers import AutoModel, AutoProcessor
from transformers.utils import logging as transformers_logging

from models.errors import RetrievalDataError

logger = logging.getLogger(__name__)

# Hub configs carry harmless validation warnings and loaders draw progress bars; keep errors only.
transformers_logging.set_verbosity_error()
transformers_logging.disable_progress_bar()

_BEIT3_BOS_ID = 0
_BEIT3_PAD_ID = 1
_BEIT3_EOS_ID = 2
_BEIT3_UNK_ID = 3
_BEIT3_SENTENCEPIECE_OFFSET = 1
_BEIT3_TOKENIZER_FILE = "beit3.spm"
_BEIT3_WEIGHTS_FILE = "beit3_base_patch16_384_coco_retrieval.pth"


def default_device() -> str:
    return "cuda" if torch.cuda.is_available() else "cpu"


def _remap_beit3_sentencepiece_ids(ids: list[int], sentencepiece_unk_id: int) -> list[int]:
    """Map raw SentencePiece IDs to the XLM-R vocabulary expected by BEiT-3."""
    return [
        _BEIT3_UNK_ID
        if token_id == sentencepiece_unk_id
        else token_id + _BEIT3_SENTENCEPIECE_OFFSET
        for token_id in ids
    ]


class EmbeddingService:
    """Text encoders of the two visual indexes (SigLIP-2 and BEiT-3).

    A model that fails to load stays disabled and raises RetrievalDataError when it is used, so
    a broken model surfaces as an error instead of silently returning meaningless results.
    """

    def __init__(
        self,
        siglip_model_id: str,
        beit3_checkpoint_dir: Path,
        device: str | None = None,
        siglip_revision: str | None = None,
    ) -> None:
        self.device = device or default_device()
        # torch modules are not guaranteed to be thread-safe; requests run in a threadpool.
        self._lock = threading.Lock()
        self.siglip_model = None
        self.siglip_processor = None
        self.siglip_error: str | None = None
        self.beit3_model = None
        self.beit3_tokenizer = None
        self.beit3_error: str | None = None
        self._load_siglip(siglip_model_id, siglip_revision or None)
        self._load_beit3(beit3_checkpoint_dir)

    def _load_siglip(self, model_id: str, revision: str | None) -> None:
        logger.debug("Loading SigLIP model %s@%s on %s", model_id, revision, self.device)
        try:
            self.siglip_processor = AutoProcessor.from_pretrained(model_id, revision=revision)
            model = AutoModel.from_pretrained(
                model_id,
                revision=revision,
                dtype=torch.float16 if self.device.startswith("cuda") else torch.float32,
                low_cpu_mem_usage=True,
            )
            self.siglip_model = model.to(self.device).eval()
            logger.info(
                "SigLIP model %s@%s loaded on %s", model_id, (revision or "main")[:12], self.device
            )
        except Exception as exc:  # noqa: BLE001 - reported through siglip_error and /health/ready
            self.siglip_error = str(exc)
            logger.exception("Failed to load SigLIP model %s", model_id)

    def _load_beit3(self, checkpoint_dir: Path) -> None:
        try:
            from infrastructure.beit3 import modeling_finetune

            logger.debug("Loading BEiT-3 tokenizer and model from %s", checkpoint_dir)
            self.beit3_tokenizer = spm.SentencePieceProcessor(
                model_file=str(checkpoint_dir / _BEIT3_TOKENIZER_FILE)
            )
            model = modeling_finetune.beit3_base_patch16_384_retrieval(pretrained=False)
            checkpoint = torch.load(
                checkpoint_dir / _BEIT3_WEIGHTS_FILE, map_location="cpu", weights_only=True
            )
            incompatible = model.load_state_dict(checkpoint["model"], strict=False)
            if incompatible.missing_keys or incompatible.unexpected_keys:
                raise RuntimeError(
                    "BEiT-3 checkpoint is incompatible with the retrieval model: "
                    f"missing={incompatible.missing_keys}, "
                    f"unexpected={incompatible.unexpected_keys}"
                )
            self.beit3_model = model.to(self.device).eval()
            logger.info("BEiT-3 model loaded from %s on %s", checkpoint_dir, self.device)
        except Exception as exc:  # noqa: BLE001 - reported through beit3_error and /health/ready
            self.beit3_model = None
            self.beit3_error = str(exc)
            logger.exception("Failed to load BEiT-3 model")

    def _get_beit3_text_segment(
        self, text_segment: str, max_len: int = 64
    ) -> tuple[torch.Tensor, torch.Tensor]:
        if max_len < 2:
            raise ValueError("BEiT-3 max_len must leave room for BOS and EOS")
        if self.beit3_tokenizer is None:
            raise RetrievalDataError("BEiT-3 tokenizer is unavailable")

        raw_ids = self.beit3_tokenizer.encode(text_segment, out_type=int)
        content_ids = _remap_beit3_sentencepiece_ids(raw_ids, self.beit3_tokenizer.unk_id())[
            : max_len - 2
        ]
        tokens = [_BEIT3_BOS_ID, *content_ids, _BEIT3_EOS_ID]
        content_length = len(tokens)
        tokens.extend([_BEIT3_PAD_ID] * (max_len - content_length))

        tokens_tensor = torch.tensor([tokens], dtype=torch.long, device=self.device)
        padding_mask = torch.tensor(
            [[False] * content_length + [True] * (max_len - content_length)],
            dtype=torch.bool,
            device=self.device,
        )
        return tokens_tensor, padding_mask

    def get_siglip_embedding(self, text: str) -> np.ndarray:
        if self.siglip_model is None:
            raise RetrievalDataError(f"SigLIP model is unavailable: {self.siglip_error}")

        logger.debug("Generating SigLIP embedding for: %s", text)
        inputs = self.siglip_processor(
            text=[text], padding="max_length", truncation=True, return_tensors="pt"
        ).to(self.device)
        with self._lock, torch.inference_mode():
            vector = self.siglip_model.text_model(**inputs).pooler_output
            vector = torch.nn.functional.normalize(vector.float(), p=2, dim=-1)
        return vector.cpu().numpy().astype(np.float32)

    def get_beit3_embedding(self, text: str) -> np.ndarray:
        if self.beit3_model is None:
            raise RetrievalDataError(f"BEiT-3 model is unavailable: {self.beit3_error}")

        logger.debug("Generating BEiT-3 embedding for: %s", text)
        tokens, padding_mask = self._get_beit3_text_segment(text)
        use_cuda = self.device.startswith("cuda")
        with (
            self._lock,
            torch.inference_mode(),
            torch.autocast(device_type="cuda" if use_cuda else "cpu", enabled=use_cuda),
        ):
            # only_infer returns (vision_cls, language_cls)
            vector = self.beit3_model(
                text_description=tokens, padding_mask=padding_mask, only_infer=True
            )[1]
            vector = torch.nn.functional.normalize(vector.float(), p=2, dim=-1)
        return vector.cpu().numpy().astype(np.float32)
