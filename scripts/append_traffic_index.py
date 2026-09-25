"""Append the traffic-camera videos (N) after the L/M/S keyframes built from data/keyframes/.

N is kept out of data/keyframes/ because its videos are VFR: the provided frame_idx
(pts_time x average fps) is only approximate, so the submission time and the frame to seek
must come from the decoded frame table instead. Run this after steps 1-4 of the README
(generate_manifest, build_faiss_index, build_es_index, build_object_index); it appends N at the
END, so the FAISS ids of L/M/S (used by Elasticsearch) never move.

Per N keyframe (row n of map-keyframes/<video_id>.csv = row n-1 of embeddings/<model>/<video_id>.npy):
  keyframe_id  <video_id>/<n:04d>
  frame_id     decoded frame index: the image of map pts_time t is the last decoded frame
               with (pts - first pts) < t + 1 s (traffic_probe/merged/frames/<video_id>.npz)
  time_ms      original pts of that frame in ms, the KIS/QA submission time
  group_id     camera id (traffic_camera/video_metadata.csv)
  image_path   traffic_keyframes/<video_id>/<n>.jpg (original BTC keyframes, outside keyframes/)
Detections objects/<video_id>/<n>.json are appended to objects_index.json by keyframe number n.

Refuses to run twice on the same manifest (it would duplicate N): re-run steps 1-4 first.
``--relink-images`` only rewrites image_path of the N keyframes already in keyframes.json (e.g.
after moving the images); the FAISS indexes do not depend on it.
``--objects-only`` re-adds N to objects_index.json after re-running only build_object_index.py
(e.g. when new object data arrives): it drops whatever that script matched for N by frame_idx
and matches N by keyframe number instead. keyframes.json and the FAISS indexes are untouched.
"""

import argparse
import csv
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import faiss
import numpy as np

INDEXES = {"siglip": "indexing/siglip.index", "beit3": "indexing/beit3.index"}


IMAGE_DIR = "traffic_keyframes"


def image_names(data_root: Path, video_id: str) -> dict[int, str]:
    """n -> file name, since BTC pads n to 3 or 4 digits."""
    folder = data_root / IMAGE_DIR / video_id
    if not folder.is_dir():
        return {}
    return {int(f.stem): f.name for f in folder.iterdir() if f.stem.isdigit()}


def traffic_entries(data_root: Path, video_id: str, rows: list[dict], camera: str) -> list[dict]:
    names = image_names(data_root, video_id)
    pts_us = np.load(data_root / "traffic_probe/merged/frames" / f"{video_id}.npz")["pts_us"]
    relative = pts_us - pts_us[0]
    entries = []
    for row in rows:
        n = int(row["n"])
        index = max(int(np.searchsorted(relative, (float(row["pts_time"]) + 1.0) * 1e6)) - 1, 0)
        entries.append({
            "keyframe_id": f"{video_id}/{n:04d}",
            "video_id": video_id,
            "frame_id": index,
            "time_ms": int(round(pts_us[index] / 1000)),
            "group_id": camera,
            "image_path": f"{IMAGE_DIR}/{video_id}/{names.get(n, f'{n:03d}.jpg')}",
        })
    return entries


def read_detections(path: Path, min_score: float) -> dict[str, tuple[float, int]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    found: dict[str, tuple[float, int]] = {}
    for label, raw in zip(data.get("detection_class_entities", []), data.get("detection_scores", []),
                          strict=False):
        score = float(raw)
        if score < min_score:
            continue
        best, count = found.get(label, (0.0, 0))
        found[label] = (max(best, score), count + 1)
    return found


def object_detections(data_root: Path, keyframe_id: str, min_score: float) -> dict[str, tuple[float, int]]:
    video_id, n = keyframe_id.split("/")
    for name in (f"{int(n):03d}.json", f"{int(n):04d}.json"):
        object_file = data_root / "objects" / video_id / name
        if object_file.exists():
            return read_detections(object_file, min_score)
    return {}


def append_objects(data_root: Path, entries: list[dict], min_score: float) -> int:
    path = data_root / "objects_index.json"
    index = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {
        "version": 1, "min_score": min_score, "labels": [], "keyframes": {}}
    # build_object_index.py may have matched N by frame_idx, which is not N's frame_id: drop it.
    index["keyframes"] = {k: v for k, v in index["keyframes"].items() if not k.startswith("N")}
    labels = index["labels"]
    label_index = {label: i for i, label in enumerate(labels)}
    keyframe_ids = [entry["keyframe_id"] for entry in entries]
    with ThreadPoolExecutor(max_workers=16) as executor:
        found = executor.map(lambda k: object_detections(data_root, k, min_score), keyframe_ids)
    added = 0
    for keyframe_id, detections in zip(keyframe_ids, found):
        if not detections:
            continue
        for label in detections:
            if label not in label_index:
                label_index[label] = len(labels)
                labels.append(label)
        index["keyframes"][keyframe_id] = [
            [label_index[label], round(score, 4), count]
            for label, (score, count) in sorted(detections.items(), key=lambda item: -item[1][0])
        ]
        added += 1
    path.write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return added


def relink_images(root: Path) -> None:
    manifest_path = root / "keyframes.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    names: dict[str, dict[int, str]] = {}
    changed, missing = 0, []
    for entry in manifest["keyframes"]:
        video_id = entry["video_id"]
        if not video_id.startswith("N"):
            continue
        if video_id not in names:
            names[video_id] = image_names(root, video_id)
        n = int(entry["keyframe_id"].split("/")[1])
        if n not in names[video_id]:
            missing.append(entry["keyframe_id"])
            continue
        path = f"{IMAGE_DIR}/{video_id}/{names[video_id][n]}"
        changed += path != entry["image_path"]
        entry["image_path"] = path
    if missing:
        raise SystemExit(f"{len(missing)} N images missing in {IMAGE_DIR}/, e.g. {missing[:3]}")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"relinked {changed} N keyframes to {IMAGE_DIR}/ ({len(names)} videos)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--min-score", type=float, default=0.3)
    parser.add_argument("--objects-only", action="store_true",
                        help="only (re)add N to objects_index.json; keyframes.json must already contain N")
    parser.add_argument("--relink-images", action="store_true",
                        help=f"only point image_path of existing N keyframes to {IMAGE_DIR}/")
    args = parser.parse_args()
    root = args.data_root
    if args.relink_images:
        relink_images(root)
        return
    if args.objects_only:
        manifest = json.loads((root / "keyframes.json").read_text(encoding="utf-8"))
        entries = [k for k in manifest["keyframes"] if k["video_id"].startswith("N")]
        if not entries:
            raise SystemExit("keyframes.json has no N keyframes: run this script without --objects-only")
        print(f"N objects re-added for {append_objects(root, entries, args.min_score)} of {len(entries)} keyframes")
        return

    manifest_path = root / "keyframes.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    base_count = len(manifest["keyframes"])
    if any(k["video_id"].startswith("N") for k in manifest["keyframes"]):
        raise SystemExit("keyframes.json already contains N: re-run README steps 1-4 first")

    indexes = {}
    for name, relative in INDEXES.items():
        index = faiss.read_index(str(root / relative))
        if index.ntotal != base_count:
            raise SystemExit(f"{relative}: ntotal {index.ntotal} != keyframes.json {base_count}")
        indexes[name] = index

    with open(root / "traffic_camera/video_metadata.csv", encoding="utf-8") as f:
        cameras = {row["video_id"]: row["camera_id"] for row in csv.DictReader(f)}

    entries, vectors = [], {name: [] for name in INDEXES}
    videos = sorted(p.stem for p in (root / "map-keyframes").glob("N*.csv"))
    for video_id in videos:
        with open(root / "map-keyframes" / f"{video_id}.csv", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        entries.extend(traffic_entries(root, video_id, rows, cameras[video_id]))
        for name, index in indexes.items():
            matrix = np.load(root / "embeddings" / name / f"{video_id}.npy").astype(np.float32)
            if matrix.shape != (len(rows), index.d):
                raise SystemExit(f"embeddings/{name}/{video_id}.npy: {matrix.shape}, need ({len(rows)}, {index.d})")
            vectors[name].append(matrix)
    missing = [e["image_path"] for e in entries if not (root / e["image_path"]).is_file()]
    if missing:
        raise SystemExit(f"{len(missing)} N keyframe images missing, e.g. {missing[:3]}")

    # Write only after every check passed.
    for name, index in indexes.items():
        matrix = np.concatenate(vectors[name])
        faiss.normalize_L2(matrix)
        index.add(matrix)
        faiss.write_index(index, str(root / INDEXES[name]))
    manifest["keyframes"].extend(entries)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    with_objects = append_objects(root, entries, args.min_score)
    print(f"N: {len(videos)} videos, {len(entries)} keyframes appended after {base_count} "
          f"(total {base_count + len(entries)}); objects for {with_objects} keyframes")


if __name__ == "__main__":
    main()
