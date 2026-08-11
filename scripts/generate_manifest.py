import argparse
import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def generate_manifest(keyframes_dir: Path, output_path: Path):
    """
    Scans the keyframes directory and generates a real manifest.json.
    Sorting MUST match the Kaggle extraction script:
    sorted(video_dirs) -> sorted(shot_dirs) -> sorted(image_files)
    """
    if not keyframes_dir.exists():
        logger.error("Keyframes directory not found at %s", keyframes_dir)
        return

    keyframes_list = []
    logger.info("Scanning directory: %s", keyframes_dir)

    for video_dir in sorted(keyframes_dir.iterdir()):
        if not video_dir.is_dir():
            continue
        video_id = video_dir.name

        for shot_dir in sorted(video_dir.iterdir()):
            if not shot_dir.is_dir():
                continue
            shot_id = shot_dir.name
            
            # Bỏ qua các thư mục không phải là shot (ví dụ: contact_sheets)
            if not shot_id.startswith("S"):
                continue

            for img_file in sorted(shot_dir.iterdir()):
                if img_file.suffix.lower() not in IMAGE_EXTENSIONS:
                    continue

                frame_id_str = img_file.stem
                if frame_id_str.upper().startswith("F"):
                    frame_id_str = frame_id_str[1:]
                try:
                    frame_id_int = int(frame_id_str)
                except ValueError:
                    frame_id_int = 0  # Fallback if filename is not purely numeric

                # Build the manifest entry
                # We use Unix-style forward slashes for relative paths
                image_path = f"keyframes/{video_id}/{shot_id}/{img_file.name}"
                keyframe_id = f"{video_id}/{shot_id}/{frame_id_str}"

                kf_entry = {
                    "keyframe_id": keyframe_id,
                    "video_id": video_id,
                    "frame_id": frame_id_int,
                    "image_path": image_path,
                    "segment_id": f"{video_id}_{shot_id}",
                    # Optional fields omitted; they can be populated later
                    # by another metadata-merging script (e.g. from ASR/OCR json)
                }
                keyframes_list.append(kf_entry)

    logger.info("Scanned %d keyframes.", len(keyframes_list))

    manifest_data = {
        "version": 1,
        "keyframes": keyframes_list
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, ensure_ascii=False, indent=2)

    logger.info("Manifest saved successfully to %s", output_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate manifest.json from keyframes folder")
    parser.add_argument("--data-root", type=str, default="./data", help="Root data directory")
    args = parser.parse_args()

    data_root = Path(args.data_root)
    keyframes_dir = data_root / "keyframes"
    manifest_path = data_root / "keyframes.json"

    generate_manifest(keyframes_dir, manifest_path)
