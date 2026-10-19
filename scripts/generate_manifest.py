import argparse
import bisect
import csv
import logging
import sys
from pathlib import Path

from _common import IMAGE_EXTENSIONS, setup_logging, write_json_atomic

logger = logging.getLogger(__name__)


def load_frame_map(data_root: Path, video_id: str) -> dict[int, int]:
    """n -> frame_idx of the provided keyframes (map-keyframes/<video_id>.csv)."""
    map_path = data_root / "map-keyframes" / f"{video_id}.csv"
    if not map_path.exists():
        return {}
    with open(map_path, encoding="utf-8") as f:
        return {int(row["n"]): int(row["frame_idx"]) for row in csv.DictReader(f)}


def load_shots(data_root: Path, video_id: str) -> list[tuple[int, int, int]]:
    """(start_frame, end_frame, scene_id) sorted by start_frame."""
    scenes_path = data_root / "scenes" / f"{video_id}.scenes.csv"
    if not scenes_path.exists():
        return []
    with open(scenes_path, encoding="utf-8") as f:
        shots = [
            (int(row["start_frame"]), int(row["end_frame"]), int(row["scene_id"]))
            for row in csv.DictReader(f)
        ]
    return sorted(shots)


def shot_for_frame(shots: list[tuple[int, int, int]], starts: list[int], frame: int) -> int:
    """scene_id of the shot containing frame; frames in a gap go to the nearest shot."""
    index = max(bisect.bisect_right(starts, frame) - 1, 0)
    if (
        frame > shots[index][1]
        and index + 1 < len(shots)
        and shots[index + 1][0] - frame < frame - shots[index][1]
    ):
        index += 1
    return shots[index][2]


def flat_keyframes(data_root: Path, video_dir: Path, image_files: list[Path]) -> list[dict]:
    """
    Keyframes stored directly in <video_id>/ (M, N, S sets): files are named by the
    provided keyframe number n, mapped to the real frame via map-keyframes.
    Sorting MUST match the Kaggle extraction script: numeric order of n.
    """
    video_id = video_dir.name
    frame_by_n = load_frame_map(data_root, video_id)
    if not frame_by_n:
        logger.warning("%s: no map-keyframes, using file names as frame ids", video_id)
    shots = load_shots(data_root, video_id)
    starts = [start for start, _, _ in shots]

    image_files.sort(key=lambda p: int(p.stem) if p.stem.isdigit() else p.name)
    entries = []
    seen_ids: set[str] = set()
    for img_file in image_files:
        try:
            n = int(img_file.stem)
        except ValueError:
            logger.warning("Skipping non-numeric keyframe %s", img_file)
            continue
        frame_id = frame_by_n.get(n)
        if frame_id is None:
            if frame_by_n:
                logger.warning("%s: no map-keyframes row for n=%d", video_id, n)
            frame_id = n

        # Zero-padded so build_faiss_index's keyframe_id sort keeps the numeric order;
        # map-keyframes can map two n to the same frame, so suffix duplicates.
        keyframe_id = f"{video_id}/{frame_id:06d}"
        duplicate = 1
        while keyframe_id in seen_ids:
            duplicate += 1
            keyframe_id = f"{video_id}/{frame_id:06d}_{duplicate}"
        seen_ids.add(keyframe_id)

        entry = {
            "keyframe_id": keyframe_id,
            "video_id": video_id,
            "frame_id": frame_id,
            "image_path": f"keyframes/{video_id}/{img_file.name}",
        }
        if shots:
            entry["segment_id"] = f"{video_id}_S{shot_for_frame(shots, starts, frame_id):05d}"
        entries.append(entry)
    return entries


def generate_manifest(keyframes_dir: Path, output_path: Path) -> bool:
    """
    Scans the keyframes directory and generates a real manifest.json.
    Sorting MUST match the Kaggle extraction script:
    sorted(video_dirs) -> sorted(shot_dirs) -> sorted(image_files)
    Shot folder images are named F<frame_idx> (L set) or by the provided keyframe
    number n (mapped through map-keyframes). Videos without shot folders (M, N, S
    sets) are handled by flat_keyframes.
    """
    data_root = keyframes_dir.parent
    if not keyframes_dir.exists():
        logger.error("Keyframes directory not found at %s", keyframes_dir)
        return False

    keyframes_list = []
    logger.info("Scanning directory: %s", keyframes_dir)

    for video_dir in sorted(keyframes_dir.iterdir()):
        if not video_dir.is_dir():
            continue
        video_id = video_dir.name

        flat_images = [
            f for f in video_dir.iterdir() if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS
        ]
        if flat_images:
            if any(d.is_dir() and d.name.startswith("S") for d in video_dir.iterdir()):
                logger.warning("%s has both flat keyframes and shot folders; using flat", video_id)
            keyframes_list.extend(flat_keyframes(data_root, video_dir, flat_images))
            continue

        # Shot folders named by provided keyframe number n (not F<frame>) need map-keyframes
        frame_by_n = None
        seen_ids: set[str] = set()

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
                else:
                    if frame_by_n is None:
                        frame_by_n = load_frame_map(data_root, video_id)
                    try:
                        n = int(frame_id_str)
                    except ValueError:
                        n = None
                    if n is not None and n in frame_by_n:
                        frame_id_int = frame_by_n[n]
                        frame_id_str = f"{frame_id_int:06d}"
                    else:
                        logger.warning("%s: cannot map %s to a frame", video_id, img_file.name)
                        frame_id_int = n or 0

                # map-keyframes can map two n to the same frame
                base_id = f"{video_id}/{shot_id}/{frame_id_str}"
                keyframe_id, duplicate = base_id, 1
                while keyframe_id in seen_ids:
                    duplicate += 1
                    keyframe_id = f"{base_id}_{duplicate}"
                seen_ids.add(keyframe_id)

                # Build the manifest entry
                # We use Unix-style forward slashes for relative paths
                image_path = f"keyframes/{video_id}/{shot_id}/{img_file.name}"

                kf_entry = {
                    "keyframe_id": keyframe_id,
                    "video_id": video_id,
                    "frame_id": frame_id_int,
                    "image_path": image_path,
                    "segment_id": f"{video_id}_{shot_id}",
                    # Optional fields omitted; they can be populated later
                    # by another metadata-merging script (e.g. from ASR json)
                }
                keyframes_list.append(kf_entry)

    logger.info("Scanned %d keyframes.", len(keyframes_list))

    manifest_data = {"version": 1, "keyframes": keyframes_list}

    write_json_atomic(output_path, manifest_data, indent=2)

    logger.info("Manifest saved successfully to %s", output_path)
    logger.info("keyframes.json changed: rebuild the FAISS, Elasticsearch and object indexes next.")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate keyframes.json from data/keyframes/")
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    args = parser.parse_args()
    setup_logging()
    ok = generate_manifest(args.data_root / "keyframes", args.data_root / "keyframes.json")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
