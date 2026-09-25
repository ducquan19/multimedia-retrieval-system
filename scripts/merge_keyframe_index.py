"""Append the organizers' keyframes of the final-round sets (N, S, M) to the manifest and FAISS.

Each run rebuilds from the preliminary-round backups (``keyframes.prelim.json`` and
``indexing/{siglip,beit3}.prelim.index``, created on the first run), then appends the groups in a
fixed order N -> S -> M. FAISS ids of earlier data never move, so ES (ASR) and the object index
stay valid, and re-running never duplicates a group. A group whose embeddings are not there yet
is skipped, so S can be merged before M is embedded.

Per group (row i of ``<embeddings>/<model>/<video_id>.npy`` = row n=i+1 of map-keyframes):
  N  thumbnails ``traffic_keyframe_thumbs/<vid>/<n:03d>.jpg``; frame_id = decoded frame index and
     time_ms = original pts (VFR, see scripts/traffic/merge_n_index.py); group_id = camera.
  S  ``Keyframes_S01/keyframes/<vid>/<n:04d>.jpg`` (M: ``<n:03d>.jpg``); frame_id = map frame_idx;
     segment_id ``<vid>_<n:04d>`` = the per-keyframe ASR window of fetch_youtube_asr.py.
  M  ``Keyframes_Mxx/keyframes/<vid>/<n:03d>.jpg``; frame_id = map frame_idx; segment_id
     ``<vid>_S<scene:05d>`` = the TransNetV2 shot containing the keyframe, the same key as
     ``asr/<vid>/S<scene:05d>.json``, so scripts/build_es_index.py indexes M's ASR by shot.

``--video-sources`` also adds the S/M videos of the public HF dataset to video_sources.json.

Example:
    python scripts/merge_keyframe_index.py --video-sources
"""

import argparse
import bisect
import csv
import json
import shutil
from pathlib import Path

import faiss
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
MODELS = {"siglip2": "indexing/siglip.index", "beit3": "indexing/beit3.index"}
PUBLIC_VIDEO_REPO = "https://huggingface.co/datasets/dwctien/aic26-videos/resolve/main/videos"


def backup_once(path: Path) -> Path:
    backup = path.with_name(path.stem + ".prelim" + path.suffix)
    if not backup.exists():
        shutil.copy2(path, backup)
        print(f"backup {path.name} -> {backup.name}")
    return backup


def read_map(map_dir: Path, video_id: str) -> list[dict]:
    with open(map_dir / f"{video_id}.csv", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def image_dirs(data_root: Path) -> dict[str, Path]:
    """video_id -> folder of original keyframes, from every data/Keyframes_*/keyframes/."""
    folders = {}
    for keyframes_dir in sorted(data_root.glob("Keyframes_*/keyframes")):
        for video_dir in keyframes_dir.iterdir():
            if video_dir.is_dir():
                folders[video_dir.name] = video_dir
    return folders


def shot_lookup(scenes_dir: Path, video_id: str):
    path = scenes_dir / f"{video_id}.scenes.csv"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        scenes = sorted((int(r["start_frame"]), int(r["scene_id"])) for r in csv.DictReader(f))
    starts = [start for start, _ in scenes]
    return lambda frame: scenes[max(bisect.bisect_right(starts, frame) - 1, 0)][1]


def n_entries(args, video_id: str, rows: list[dict], cameras: dict[str, str]) -> list[dict]:
    pts_us = np.load(args.frames_dir / f"{video_id}.npz")["pts_us"]
    relative = pts_us - pts_us[0]
    entries = []
    for row in rows:
        n = int(row["n"])
        # The image of map pts_time t is the last decoded frame before t + 1 s.
        index = max(int(np.searchsorted(relative, (float(row["pts_time"]) + 1.0) * 1e6)) - 1, 0)
        entries.append({
            "keyframe_id": f"{video_id}/{n:04d}",
            "video_id": video_id,
            "frame_id": index,
            "time_ms": int(round(pts_us[index] / 1000)),
            "group_id": cameras[video_id],
            "image_path": f"traffic_keyframe_thumbs/{video_id}/{n:03d}.jpg",
        })
    return entries


def provided_entries(args, video_id: str, rows: list[dict], folders: dict[str, Path]) -> list[dict]:
    folder = folders.get(video_id)
    if folder is None:
        raise SystemExit(f"{video_id}: no data/Keyframes_*/keyframes/{video_id}/ folder")
    shot_of = shot_lookup(args.scenes_dir, video_id) if video_id.startswith("M") else None
    # BTC names images with 3 (M) or 4 (S) digits, so map n to the real file name.
    names = {int(f.stem): f.name for f in folder.iterdir() if f.stem.isdigit()}
    entries = []
    for row in rows:
        n, frame_idx = int(row["n"]), int(row["frame_idx"])
        entry = {
            "keyframe_id": f"{video_id}/{n:04d}",
            "video_id": video_id,
            "frame_id": frame_idx,
            "image_path": (folder / names.get(n, f"{n:04d}.jpg")).relative_to(args.data_root).as_posix(),
        }
        if shot_of is not None:
            entry["segment_id"] = f"{video_id}_S{shot_of(frame_idx):05d}"
        elif video_id.startswith("S"):
            entry["segment_id"] = f"{video_id}_{n:04d}"
        entries.append(entry)
    return entries


def asr_text(data_root: Path, entry: dict) -> str | None:
    segment = entry.get("segment_id")
    if not segment:
        return None
    video_id, _, key = segment.rpartition("_")
    path = data_root / "asr" / video_id / f"{key}.json"
    if not path.exists():
        return None
    text = json.loads(path.read_text(encoding="utf-8")).get("text", "").strip()
    return text or None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-root", type=Path, default=ROOT / "data")
    parser.add_argument("--map-dir", type=Path, default=ROOT / "data/aic26-b2-map-keyframes/map-keyframes")
    parser.add_argument("--frames-dir", type=Path, default=ROOT / "data/traffic_probe/merged/frames")
    parser.add_argument("--scenes-dir", type=Path, default=ROOT / "data/transnetv2_results_batch2/scenes")
    parser.add_argument("--cameras", type=Path, default=ROOT / "data/traffic_camera/video_metadata.csv")
    parser.add_argument("--groups", nargs="+", default=["N", "S", "M"], choices=["N", "S", "M"])
    parser.add_argument("--embeddings", nargs="+", default=["N=data/embeddings_n", "S=data/embeddings_s",
                                                             "M=data/embeddings_m"],
                        help="GROUP=dir with <model>/<video_id>.npy")
    parser.add_argument("--video-sources", action="store_true", help="add S/M to video_sources.json")
    args = parser.parse_args()

    embedding_dirs = {g: ROOT / d if not Path(d).is_absolute() else Path(d)
                      for g, d in (item.split("=", 1) for item in args.embeddings)}
    manifest_path = args.data_root / "keyframes.json"
    manifest = json.loads(backup_once(manifest_path).read_text(encoding="utf-8"))
    base_count = len(manifest["keyframes"])
    if any(k["video_id"][0] in "NSM" for k in manifest["keyframes"]):
        raise SystemExit("keyframes.prelim.json already contains N/S/M keyframes")
    indexes = {}
    for model, relative in MODELS.items():
        index = faiss.read_index(str(backup_once(args.data_root / relative)))
        if index.ntotal != base_count:
            raise SystemExit(f"{relative}: ntotal {index.ntotal} != manifest {base_count}")
        indexes[model] = index

    with open(args.cameras, encoding="utf-8") as f:
        cameras = {r["video_id"]: r["camera_id"] for r in csv.DictReader(f)}
    folders = image_dirs(args.data_root)
    merged_groups = []
    for group in args.groups:
        emb_dir = embedding_dirs[group]
        videos = sorted(p.stem for p in args.map_dir.glob(f"{group}*.csv"))
        missing = [v for v in videos for m in MODELS if not (emb_dir / m / f"{v}.npy").exists()]
        if missing:
            print(f"skip {group}: {len(set(missing))}/{len(videos)} videos without embeddings in {emb_dir}")
            continue
        entries, vectors = [], {m: [] for m in MODELS}
        for video_id in videos:
            rows = read_map(args.map_dir, video_id)
            video_entries = (n_entries(args, video_id, rows, cameras) if group == "N"
                             else provided_entries(args, video_id, rows, folders))
            for model, index in indexes.items():
                matrix = np.load(emb_dir / model / f"{video_id}.npy").astype(np.float32)
                if matrix.shape != (len(rows), index.d):
                    raise SystemExit(f"{model}/{video_id}.npy: {matrix.shape}, need ({len(rows)}, {index.d})")
                vectors[model].append(matrix)
            entries.extend(video_entries)
        absent = [e["image_path"] for e in entries if not (args.data_root / e["image_path"]).is_file()]
        if absent:
            raise SystemExit(f"{group}: {len(absent)} keyframe images missing, e.g. {absent[:3]}")
        with_asr = 0
        for entry in entries:
            text = asr_text(args.data_root, entry)
            if text:
                entry["asr_text"] = text
                with_asr += 1
        for model, index in indexes.items():
            matrix = np.concatenate(vectors[model])
            faiss.normalize_L2(matrix)
            index.add(matrix)
        manifest["keyframes"].extend(entries)
        merged_groups.append(group)
        print(f"{group}: {len(videos)} videos, {len(entries)} keyframes, ASR on {with_asr}")

    # Write only after every check passed.
    for model, relative in MODELS.items():
        faiss.write_index(indexes[model], str(args.data_root / relative))
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{manifest_path.name}: {base_count} prelim + {len(manifest['keyframes']) - base_count} = "
          f"{len(manifest['keyframes'])} keyframes ({', '.join(merged_groups) or 'no group'})")

    if args.video_sources:
        sources_path = args.data_root / "video_sources.json"
        sources = json.loads(sources_path.read_text(encoding="utf-8"))
        added = 0
        for map_csv in sorted(args.map_dir.glob("*.csv")):
            video_id = map_csv.stem
            if video_id[0] not in "SM":
                continue
            fps = float(read_map(args.map_dir, video_id)[0]["fps"])
            sources["videos"][video_id] = {"remote_url": f"{PUBLIC_VIDEO_REPO}/{video_id}.mp4", "fps": fps}
            added += 1
        sources["videos"] = dict(sorted(sources["videos"].items()))
        sources_path.write_text(json.dumps(sources, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{sources_path.name}: set {added} S/M videos")


if __name__ == "__main__":
    main()
