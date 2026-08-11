import argparse
import json
import logging
from collections import defaultdict
from pathlib import Path

import faiss
import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def build_faiss_index(
    embedding_dir: Path, manifest_path: Path, output_index_path: Path, dimension: int = 512
):
    """
    Builds a FAISS index from video-level .npy files (N, D).
    To ensure the faiss_id exactly matches the global keyframe index in manifest.json:
    1. Group manifest keyframes by video_id.
    2. Sort them by keyframe_id (matching the alphabetical sort used during extraction).
    3. Map row `i` of video_id.npy to the `global_index` of the sorted manifest keyframe.
    """
    logger.info("Loading manifest from %s", manifest_path)
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    except Exception as e:
        logger.error("Failed to load manifest: %s", e)
        return

    keyframes = manifest.get("keyframes", [])
    if not keyframes:
        logger.warning("No keyframes found in manifest.")
        return

    total_frames = len(keyframes)
    logger.info("Total keyframes in manifest: %d", total_frames)

    # 1. Group keyframes by video_id
    video_to_frames = defaultdict(list)
    for global_idx, kf in enumerate(keyframes):
        video_id = kf["video_id"]
        # Lưu lại global_idx để sau này gán vector vào đúng vị trí tổng
        video_to_frames[video_id].append({
            "global_idx": global_idx,
            "keyframe_id": kf["keyframe_id"],
            "video_id": video_id
        })

    # 2. Sort frames within each video (must match extraction logic)
    for video_id in video_to_frames:
        # Sort alphabetically by keyframe_id (e.g., L01_V001/S001/0001)
        video_to_frames[video_id].sort(key=lambda x: x["keyframe_id"])

    # Prepare an empty array for all vectors
    # Using np.zeros allows us to keep the index aligned even if some files are missing
    all_vectors = np.zeros((total_frames, dimension), dtype=np.float32)
    missing_videos = 0
    mismatched_frames = 0

    # 3. Read .npy files and populate all_vectors
    for video_id, frames_metadata in video_to_frames.items():
        npy_path = embedding_dir / f"{video_id}.npy"

        if not npy_path.exists():
            logger.warning("Missing embedding file for video %s: %s", video_id, npy_path)
            missing_videos += 1
            continue

        try:
            # .npy file should have shape (N, D)
            video_vectors = np.load(npy_path)

            if video_vectors.ndim == 1:
                video_vectors = video_vectors.reshape(1, -1)

            N, D = video_vectors.shape
            expected_N = len(frames_metadata)

            if D != dimension:
                logger.error("Video %s has wrong dimension: %d (expected %d)", video_id, D, dimension)
                continue

            if N != expected_N:
                logger.warning(
                    "Video %s frame count mismatch: .npy has %d, manifest expects %d",
                    video_id, N, expected_N
                )
                mismatched_frames += abs(N - expected_N)

            # Copy vectors to their global positions
            # If N < expected_N, we only copy N vectors
            # If N > expected_N, we only copy expected_N vectors
            limit = min(N, expected_N)
            for i in range(limit):
                global_idx = frames_metadata[i]["global_idx"]
                all_vectors[global_idx] = video_vectors[i]

        except Exception as e:
            logger.error("Error processing %s: %s", npy_path, e)
            missing_videos += 1

    # 4. Normalize L2 (required for Inner Product to act as Cosine Similarity)
    logger.info("Normalizing all vectors (L2)...")
    faiss.normalize_L2(all_vectors)

    # 5. Build FAISS Index
    logger.info("Building FAISS FlatIP index...")
    index = faiss.IndexFlatIP(dimension)
    index.add(all_vectors)

    logger.info("Finished. Total indexed vectors: %d (Missing videos: %d, Mismatched frames: %d)",
                index.ntotal, missing_videos, mismatched_frames)

    # Save the index
    output_index_path.parent.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(output_index_path))
    logger.info("Saved index to %s", output_index_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build FAISS Index from video-level embeddings")
    parser.add_argument("--data-root", type=str, default="./data", help="Root data directory")
    parser.add_argument("--dim-siglip", type=int, default=1152, help="SigLIP Embedding dimension")
    parser.add_argument("--dim-beit3", type=int, default=768, help="BEiT Embedding dimension")
    args = parser.parse_args()

    data_root = Path(args.data_root)
    manifest_path = data_root / "manifest.json"

    # Build SigLIP Index
    siglip_dir = data_root / "embeddings" / "siglip"
    if siglip_dir.exists():
        logger.info("--- Building SigLIP Index ---")
        build_faiss_index(siglip_dir, manifest_path, data_root / "indexing" / "siglip.index", dimension=args.dim_siglip)
    else:
        logger.warning("SigLIP embedding dir not found: %s", siglip_dir)

    # Build BEiT3 Index
    beit3_dir = data_root / "embeddings" / "beit3"
    if beit3_dir.exists():
        logger.info("--- Building BEiT3 Index ---")
        build_faiss_index(beit3_dir, manifest_path, data_root / "indexing" / "beit3.index", dimension=args.dim_beit3)
    else:
        logger.warning("BEiT3 embedding dir not found: %s", beit3_dir)
