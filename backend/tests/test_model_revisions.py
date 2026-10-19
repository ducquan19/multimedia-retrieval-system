"""Query and keyframe embeddings must come from the same model weights and preprocessing."""

import json
import re
from pathlib import Path

from core.config import Settings

ROOT = Path(__file__).resolve().parents[2]


def test_backend_and_keyframe_embedding_use_the_same_siglip_revision() -> None:
    script = (ROOT / "scripts" / "embed_keyframes.py").read_text(encoding="utf-8")
    script_revision = re.search(r'^SIGLIP2_REVISION = "([0-9a-f]{40})"$', script, re.M)
    notebook = json.loads((ROOT / "notebooks" / "embed_siglip2.ipynb").read_text(encoding="utf-8"))
    notebook_source = "".join(line for cell in notebook["cells"] for line in cell["source"])
    notebook_revision = re.search(r'^MODEL_REVISION = "([0-9a-f]{40})"$', notebook_source, re.M)

    backend_revision = Settings.model_fields["siglip_model_revision"].default
    assert script_revision and notebook_revision
    assert backend_revision == script_revision.group(1) == notebook_revision.group(1)
