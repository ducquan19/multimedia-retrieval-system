"""Build the object-detection index used by the Object search source.

Inputs (all below the data root):
- keyframes.json                      searchable keyframes (the FAISS order)
- objects/<video_id>/<n>.json         detections of the n-th provided keyframe
- map-keyframes/<video_id>.csv        n -> frame_idx of the provided keyframes
- scenes/<video_id>.scenes.csv        shot boundaries

Keyframes that are provided keyframes (M, N, S sets) are matched by exact
frame_idx. Keyframes extracted locally do not line up with the provided ones:
detections of every provided keyframe are merged per shot and assigned to all
local keyframes in that shot. This is forced for --shot-level-prefixes (L set) and
is the per-keyframe fallback for other videos with scenes, so M videos split into
shot folders get objects either way.

Output: objects_index.json
{
  "version": 1,
  "min_score": 0.3,
  "labels": ["Person", ...],
  "keyframes": {"<keyframe_id>": [[label_index, max_score, max_count], ...]}
}
"""

import argparse
import bisect
import csv
import json
import logging
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from _common import write_json_atomic

logger = logging.getLogger(__name__)

# label -> (max score, max instance count in a single frame)
Detections = dict[str, tuple[float, int]]


def read_frame_detections(path: Path, min_score: float) -> Detections:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    counts: dict[str, int] = defaultdict(int)
    scores: dict[str, float] = {}
    for label, raw_score in zip(
        data.get("detection_class_entities", []),
        data.get("detection_scores", []),
        strict=False,
    ):
        score = float(raw_score)
        if score < min_score:
            continue
        counts[label] += 1
        scores[label] = max(scores.get(label, 0.0), score)
    return {label: (scores[label], counts[label]) for label in scores}


def merge_detections(target: Detections, source: Detections) -> None:
    for label, (score, count) in source.items():
        old_score, old_count = target.get(label, (0.0, 0))
        target[label] = (max(old_score, score), max(old_count, count))


def read_provided_keyframes(
    data_root: Path, video_id: str, min_score: float
) -> list[tuple[int, Detections]]:
    """Return (frame_idx, detections) of every provided keyframe of a video."""
    map_path = data_root / "map-keyframes" / f"{video_id}.csv"
    objects_dir = data_root / "objects" / video_id
    if not map_path.exists() or not objects_dir.exists():
        return []

    with open(map_path, encoding="utf-8") as f:
        frame_by_n = {int(row["n"]): int(row["frame_idx"]) for row in csv.DictReader(f)}

    provided = []
    for object_file in objects_dir.glob("*.json"):
        try:
            n = int(object_file.stem)
        except ValueError:
            continue
        frame_idx = frame_by_n.get(n)
        if frame_idx is None:
            logger.warning("%s has no map-keyframes row for n=%d", video_id, n)
            continue
        provided.append((frame_idx, read_frame_detections(object_file, min_score)))
    provided.sort(key=lambda item: item[0])
    return provided


def read_shots(data_root: Path, video_id: str) -> list[tuple[int, int]]:
    scenes_path = data_root / "scenes" / f"{video_id}.scenes.csv"
    if not scenes_path.exists():
        return []
    with open(scenes_path, encoding="utf-8") as f:
        shots = [(int(row["start_frame"]), int(row["end_frame"])) for row in csv.DictReader(f)]
    shots.sort()
    return shots


def shot_index(shots: list[tuple[int, int]], starts: list[int], frame: int) -> int:
    """Index of the shot containing frame; frames in a gap go to the nearest shot."""
    index = max(bisect.bisect_right(starts, frame) - 1, 0)
    if frame > shots[index][1] and index + 1 < len(shots):
        gap_before = frame - shots[index][1]
        gap_after = shots[index + 1][0] - frame
        if gap_after < gap_before:
            index += 1
    return index


def build_video(
    data_root: Path,
    video_id: str,
    keyframes: list[dict],
    shot_level: bool,
    min_score: float,
) -> tuple[dict[str, Detections], str]:
    provided = read_provided_keyframes(data_root, video_id, min_score)
    if not provided:
        return {}, "no_objects"

    # map-keyframes can map several provided keyframes to the same frame
    by_frame: dict[int, Detections] = defaultdict(dict)
    for frame_idx, detections in provided:
        merge_detections(by_frame[frame_idx], detections)

    shots = read_shots(data_root, video_id)
    starts = [start for start, _ in shots]
    by_shot: dict[int, Detections] = defaultdict(dict)
    for frame_idx, detections in provided:
        if shots:
            merge_detections(by_shot[shot_index(shots, starts, frame_idx)], detections)

    result = {}
    exact = merged = 0
    for keyframe in keyframes:
        frame = keyframe["frame_id"]
        # Provided keyframes match exactly; locally extracted ones fall back to their shot
        if not shot_level and frame in by_frame:
            detections = by_frame[frame]
            exact += 1
        elif shots:
            detections = by_shot.get(shot_index(shots, starts, frame))
            merged += 1
        else:
            detections = None
        if detections:
            result[keyframe["keyframe_id"]] = detections

    if exact and merged:
        mode = "mixed"
    elif exact:
        mode = "frame"
    elif merged:
        mode = "shot"
    else:
        mode = "no_match"
    return result, mode


def build_object_index(
    data_root: Path,
    output_path: Path,
    min_score: float,
    shot_level_prefixes: tuple[str, ...],
    workers: int,
) -> None:
    keyframes_path = data_root / "keyframes.json"
    logger.info("Loading %s...", keyframes_path)
    with open(keyframes_path, encoding="utf-8") as f:
        keyframes = json.load(f)["keyframes"]

    keyframes_by_video: dict[str, list[dict]] = defaultdict(list)
    for keyframe in keyframes:
        keyframes_by_video[keyframe["video_id"]].append(keyframe)
    logger.info(
        "Mapping objects for %d keyframes in %d videos...",
        len(keyframes),
        len(keyframes_by_video),
    )

    def job(item: tuple[str, list[dict]]) -> tuple[str, dict[str, Detections], str]:
        video_id, video_keyframes = item
        shot_level = video_id.startswith(shot_level_prefixes)
        detections, mode = build_video(data_root, video_id, video_keyframes, shot_level, min_score)
        return video_id, detections, mode

    all_detections: dict[str, Detections] = {}
    modes: dict[str, int] = defaultdict(int)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for done, (video_id, detections, mode) in enumerate(
            executor.map(job, sorted(keyframes_by_video.items())), start=1
        ):
            all_detections.update(detections)
            modes[mode] += 1
            if mode in {"no_objects", "no_match"}:
                logger.warning("%s: %s", video_id, mode)
            if done % 100 == 0:
                logger.info("Processed %d/%d videos", done, len(keyframes_by_video))

    labels = sorted({label for detections in all_detections.values() for label in detections})
    label_index = {label: index for index, label in enumerate(labels)}
    output = {
        "version": 1,
        "min_score": min_score,
        "labels": labels,
        "keyframes": {
            keyframe_id: [
                [label_index[label], round(score, 4), count]
                for label, (score, count) in sorted(
                    detections.items(), key=lambda item: item[1][0], reverse=True
                )
            ]
            for keyframe_id, detections in all_detections.items()
        },
    }

    write_json_atomic(output_path, output, separators=(",", ":"))

    logger.info("Videos by mapping mode: %s", dict(modes))
    logger.info(
        "Keyframes with objects: %d/%d, labels: %d",
        len(all_detections),
        len(keyframes),
        len(labels),
    )
    logger.info("Object index saved to %s", output_path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--output", type=Path, help="Default: <data-root>/objects_index.json")
    parser.add_argument("--min-score", type=float, default=0.3)
    parser.add_argument(
        "--shot-level-prefixes",
        nargs="+",
        default=["L"],
        help="Video ID prefixes whose keyframes receive shot-level objects",
    )
    parser.add_argument("--workers", type=int, default=16)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    if not (args.data_root / "keyframes.json").exists():
        logger.error("keyframes.json not found in %s", args.data_root)
        return 1
    build_object_index(
        args.data_root,
        args.output or args.data_root / "objects_index.json",
        args.min_score,
        tuple(args.shot_level_prefixes),
        args.workers,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
