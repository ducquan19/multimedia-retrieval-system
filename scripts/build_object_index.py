"""Build data/objects_index.json from the organizers' object detections.

Input directories follow the BTC layout ``{dir}/{video_id}/{n}.json`` (Open Images detector:
``detection_class_entities`` + ``detection_scores``), where ``n`` is the keyframe number of
``map-keyframes/{video_id}.csv``. The matching manifest keyframe is ``{video_id}/{n:04d}``, as
written by scripts/traffic/merge_n_index.py; detections of keyframes missing from the manifest
are skipped.

Output (read by backend KeyframeObjectRepository):
    {"labels": [...], "keyframes": {keyframe_id: [[label_index, max_score, count], ...]}}
``count`` is the number of instances with score >= --min-score.
"""

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--objects-dir", type=Path, nargs="+", default=[Path("data/Objects_N001_N100")])
    parser.add_argument("--min-score", type=float, default=0.3)
    parser.add_argument("--output", type=Path, default=Path("data/objects_index.json"))
    args = parser.parse_args()

    manifest = json.loads((args.data_root / "keyframes.json").read_text(encoding="utf-8"))
    known = {k["keyframe_id"] for k in manifest["keyframes"]}

    labels: list[str] = []
    label_index: dict[str, int] = {}
    keyframes: dict[str, list[list]] = {}
    skipped = 0
    for objects_dir in args.objects_dir:
        for path in sorted(objects_dir.glob("*/*.json")):
            keyframe_id = f"{path.parent.name}/{int(path.stem):04d}"
            if keyframe_id not in known:
                skipped += 1
                continue
            raw = json.loads(path.read_text(encoding="utf-8"))
            best: dict[int, list] = {}
            for entity, score in zip(raw["detection_class_entities"], raw["detection_scores"], strict=True):
                score = float(score)
                if score < args.min_score:
                    continue
                if entity not in label_index:
                    label_index[entity] = len(labels)
                    labels.append(entity)
                entry = best.setdefault(label_index[entity], [label_index[entity], 0.0, 0])
                entry[1] = max(entry[1], round(score, 4))
                entry[2] += 1
            if best:
                keyframes[keyframe_id] = list(best.values())

    args.output.write_text(json.dumps({"labels": labels, "keyframes": keyframes}), encoding="utf-8")
    print(f"{args.output}: {len(keyframes)} keyframes, {len(labels)} labels, skipped {skipped} files")


if __name__ == "__main__":
    main()
