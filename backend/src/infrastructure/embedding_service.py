import logging
import sys
from pathlib import Path

import numpy as np
import sentencepiece as spm
import torch
from transformers import AutoModel, AutoProcessor

logger = logging.getLogger(__name__)

_BEIT3_BOS_ID = 0
_BEIT3_PAD_ID = 1
_BEIT3_EOS_ID = 2
_BEIT3_UNK_ID = 3
_BEIT3_SENTENCEPIECE_OFFSET = 1


def _remap_beit3_sentencepiece_ids(ids: list[int], sentencepiece_unk_id: int) -> list[int]:
    """Map raw SentencePiece IDs to the XLM-R vocabulary expected by BEiT-3."""
    return [
        _BEIT3_UNK_ID
        if token_id == sentencepiece_unk_id
        else token_id + _BEIT3_SENTENCEPIECE_OFFSET
        for token_id in ids
    ]


class EmbeddingService:
    """An embedding service to convert text to vectors using real HuggingFace models."""
    def __init__(
        self,
        siglip_model_id: str = "google/siglip2-so400m-patch14-384",
        beit3_model_path: str = "./data/checkpoint",
        device: str = "cuda" if torch.cuda.is_available() else "cpu"
    ) -> None:
        self.device = device

        # Load SigLIP (Supports Vietnamese via WebLI multilingual pre-training)
        logger.info(f"Loading SigLIP model: {siglip_model_id} on {self.device}")
        try:
            self.siglip_processor = AutoProcessor.from_pretrained(siglip_model_id)
            self.siglip_model = AutoModel.from_pretrained(
                siglip_model_id,
                trust_remote_code=True,
                torch_dtype=torch.float16,
                low_cpu_mem_usage=True
            ).to(self.device)
            self.siglip_model.eval()
            logger.info("SigLIP model loaded successfully!")
        except Exception as e:
            logger.error("Failed to load SigLIP model: %s", e)
            self.siglip_model = None

        # Load BEiT-3 (English-centric from COCO, fine-tuned for ITC)
        self.beit3_model = None
        self.beit3_tokenizer = None

        try:
            spm_path = Path(beit3_model_path) / "beit3.spm"
            pth_path = Path(beit3_model_path) / "beit3_base_patch16_384_coco_retrieval.pth"

            # Add BEiT-3 to path to load its modules
            beit3_dir = str(Path(__file__).parent / "beit3")
            if beit3_dir not in sys.path:
                sys.path.append(beit3_dir)
            from infrastructure.beit3 import modeling_finetune

            logger.info("Loading BEiT-3 Tokenizer and Model...")
            self.beit3_tokenizer = spm.SentencePieceProcessor(model_file=str(spm_path))
            self.beit3_model = modeling_finetune.beit3_base_patch16_384_retrieval(pretrained=False)
            checkpoint = torch.load(pth_path, map_location="cpu", weights_only=True)
            incompatible = self.beit3_model.load_state_dict(checkpoint["model"], strict=False)
            if incompatible.missing_keys or incompatible.unexpected_keys:
                raise RuntimeError(
                    "BEiT-3 checkpoint is incompatible with the retrieval model: "
                    f"missing={incompatible.missing_keys}, "
                    f"unexpected={incompatible.unexpected_keys}"
                )
            self.beit3_model = self.beit3_model.to(self.device).eval()
            logger.info("BEiT-3 ITC Model loaded successfully!")
        except Exception as e:
            self.beit3_model = None
            logger.exception("Failed to load BEiT-3 model: %s", e)

    def _get_beit3_text_segment(
        self, text_segment: str, max_len: int = 64
    ) -> tuple[torch.Tensor, torch.Tensor]:
        if max_len < 2:
            raise ValueError("BEiT-3 max_len must leave room for BOS and EOS")
        if self.beit3_tokenizer is None:
            raise RuntimeError("BEiT-3 tokenizer is unavailable")

        raw_ids = self.beit3_tokenizer.encode(text_segment, out_type=int)
        content_ids = _remap_beit3_sentencepiece_ids(
            raw_ids, self.beit3_tokenizer.unk_id()
        )[: max_len - 2]
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
        if not self.siglip_model:
            return np.zeros((1, 1152), dtype='float32')

        logger.debug("Generating SigLIP embedding for: %s", text)
        inputs = self.siglip_processor(text=[text], padding="max_length", truncation=True, return_tensors="pt").to(self.device)
        with torch.no_grad():
            text_outputs = self.siglip_model.text_model(**inputs)
            vector = text_outputs.pooler_output  # (1, 1152)
            vector = torch.nn.functional.normalize(vector, p=2, dim=-1)
        return vector.cpu().numpy().astype('float32')

    def get_beit3_embedding(self, text: str) -> np.ndarray:
        if not self.beit3_model:
            raise RuntimeError("BEiT-3 was selected but its retrieval model is unavailable")

        logger.debug("Generating BEiT3 embedding for: %s", text)

        tokens, padding_mask = self._get_beit3_text_segment(text)

        with torch.no_grad(), torch.autocast(device_type="cuda" if "cuda" in self.device else "cpu", enabled=("cuda" in self.device)):
            outputs = self.beit3_model(
                text_description=tokens,
                padding_mask=padding_mask,
                only_infer=True
            )
            # outputs is (vision_cls, language_cls), so we take [1]
            vector = outputs[1]
            vector = torch.nn.functional.normalize(vector, p=2, dim=-1)

        vector = vector.cpu().numpy().astype('float32')
        return vector
