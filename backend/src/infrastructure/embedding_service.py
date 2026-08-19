import logging
from pathlib import Path

import numpy as np
import torch
from transformers import AutoModel, AutoProcessor

logger = logging.getLogger(__name__)


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

            import sys
            import sentencepiece as spm

            # Add BEiT-3 to path to load its modules
            beit3_dir = str(Path(__file__).parent / "beit3")
            if beit3_dir not in sys.path:
                sys.path.append(beit3_dir)
            from infrastructure.beit3 import modeling_finetune

            logger.info("Loading BEiT-3 Tokenizer and Model...")
            self.beit3_tokenizer = spm.SentencePieceProcessor(model_file=str(spm_path))
            self.beit3_model = modeling_finetune.beit3_base_patch16_384_retrieval(pretrained=False)
            checkpoint = torch.load(pth_path, map_location="cpu")
            self.beit3_model.load_state_dict(checkpoint['model'], strict=False)
            self.beit3_model = self.beit3_model.to(self.device).eval()
            logger.info("BEiT-3 ITC Model loaded successfully!")
        except Exception as e:
            logger.error("Failed to load BEiT-3 model: %s", e)

    def _get_beit3_text_segment(self, text_segment: str, max_len: int = 64):
        # Manually encode using SentencePiece
        ids = self.beit3_tokenizer.encode(text_segment)

        # Add BOS (0) and EOS (2)
        tokens = [0] + ids + [2]

        # Truncate if necessary
        if len(tokens) > max_len:
            tokens = tokens[:max_len - 1] + [2]

        # Pad if necessary with PAD (1)
        attention_mask = [1] * len(tokens)
        if len(tokens) < max_len:
            pad_len = max_len - len(tokens)
            tokens.extend([1] * pad_len)
            attention_mask.extend([0] * pad_len)

        tokens_tensor = torch.tensor([tokens], dtype=torch.long, device=self.device)
        # In BEiT3, padding_mask is True for padding tokens (where attention_mask is 0)
        attention_mask_tensor = torch.tensor([attention_mask], dtype=torch.long, device=self.device)
        padding_mask = (attention_mask_tensor == 0).to(self.device)
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
            # BEiT-3 Base ITC uses 768 dimension
            return np.zeros((1, 768), dtype='float32')

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
