"""Build the FAISS indexes (SigLIP, BEiT-3) from per-video embedding files.

Input:  <data-root>/embeddings/<model>/<video_id>.npy, shape (N, D), row i = i-th keyframe of
        the video in keyframe_id order (the order embed_keyframes.py writes).
Output: <data-root>/indexing/<model>.index (IndexFlatIP) where row i = keyframes.json[i], plus
        <model>.index.meta.json with the keyframe order hash checked by the backend at startup.

The build stops when a video's .npy is missing or has a different number of rows than the
manifest: copying rows by position would silently attach vectors to the wrong keyframes.
``--allow-missing`` only tolerates missing videos (their keyframes get zero vectors and can
never be found visually); a row count mismatch is always an error.

Example:
    python scripts/build_faiss_index.py --data-root data
"""

import argparse
import json
import logging
import sys
from collections import defaultdict
from pathlib import Path

import faiss
import numpy as np

from _common import atomic_path, setup_logging, write_index_meta

logger = logging.getLogger(__name__)

MODELS = {"siglip": 1152, "beit3": 768}


class IndexBuildError(RuntimeError):
    pass


def build_faiss_index(
    embedding_dir: Path,
    keyframes: list[dict],
    output_index_path: Path,
    dimension: int,
    allow_missing: bool = False,
) -> int:
    """Build one index; returns the number of videos without embeddings (zero vectors)."""
    # Group keyframes by video, remembering each keyframe's global position (= FAISS id).
    video_to_positions: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for position, keyframe in enumerate(keyframes):
        video_to_positions[keyframe["video_id"]].append((keyframe["keyframe_id"], position))

    all_vectors = np.zeros((len(keyframes), dimension), dtype=np.float32)
    missing: list[str] = []
    problems: list[str] = []
    for video_id, entries in sorted(video_to_positions.items()):
        # Rows follow keyframe_id order within the video (zero-padded ids sort numerically).
        entries.sort()
        npy_path = embedding_dir / f"{video_id}.npy"
        if not npy_path.exists():
            missing.append(video_id)
            continue
        vectors = np.load(npy_path)
        if vectors.ndim == 1:
            vectors = vectors.reshape(1, -1)
        if vectors.shape != (len(entries), dimension):
            problems.append(
                f"{video_id}: {npy_path.name} has shape {vectors.shape}, "
                f"expected ({len(entries)}, {dimension})"
            )
            continue
        all_vectors[[position for _, position in entries]] = vectors

    if problems:
        raise IndexBuildError(
            f"{len(problems)} videos do not match keyframes.json:\n  " + "\n  ".join(problems[:20])
        )
    if missing:
        message = f"{len(missing)} videos have no embeddings, e.g. {missing[:10]}"
        if not allow_missing:
            raise IndexBuildError(message + " (use --allow-missing to index them as zeros)")
        logger.warning("%s; their keyframes get zero vectors", message)

    # The extraction scripts L2-normalize already; re-normalize defensively (IP = cosine).
    faiss.normalize_L2(all_vectors)
    index = faiss.IndexFlatIP(dimension)
    index.add(all_vectors)

    with atomic_path(output_index_path) as tmp:
        faiss.write_index(index, str(tmp))
    meta_path = write_index_meta(
        output_index_path,
        ntotal=index.ntotal,
        dim=dimension,
        keyframe_ids=[keyframe["keyframe_id"] for keyframe in keyframes],
    )
    logger.info("Saved %s (%d vectors) and %s", output_index_path, index.ntotal, meta_path.name)
    return len(missing)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--models", nargs="+", choices=sorted(MODELS), default=sorted(MODELS))
    parser.add_argument("--dim-siglip", type=int, default=MODELS["siglip"])
    parser.add_argument("--dim-beit3", type=int, default=MODELS["beit3"])
    parser.add_argument("--allow-missing", action="store_true")
    args = parser.parse_args()
    setup_logging()

    manifest_path = args.data_root / "keyframes.json"
    try:
        keyframes = json.loads(manifest_path.read_text(encoding="utf-8"))["keyframes"]
    except (OSError, ValueError, KeyError) as exc:
        logger.error("Cannot read %s: %s", manifest_path, exc)
        return 1
    if not keyframes:
        logger.error("%s has no keyframes", manifest_path)
        return 1
    logger.info("%d keyframes in %s", len(keyframes), manifest_path)

    dims = {"siglip": args.dim_siglip, "beit3": args.dim_beit3}
    for model in args.models:
        embedding_dir = args.data_root / "embeddings" / model
        if not embedding_dir.is_dir():
            logger.error("Embedding folder not found: %s", embedding_dir)
            return 1
        logger.info("--- Building %s index ---", model)
        try:
            build_faiss_index(
                embedding_dir,
                keyframes,
                args.data_root / "indexing" / f"{model}.index",
                dims[model],
                args.allow_missing,
            )
        except IndexBuildError as exc:
            logger.error("%s index not written: %s", model, exc)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
