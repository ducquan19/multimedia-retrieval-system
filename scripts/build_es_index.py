"""Build the Elasticsearch BM25 index of ASR transcripts (index "keyframes_metadata").

Every keyframe whose shot has ASR text becomes a document with _id = its position in
keyframes.json (the FAISS id). keyframes.json is only read: the transcripts the UI shows are
written to data/asr_texts.json (video_id -> segment_id -> text), which the backend merges in
when it loads the manifest.

The index mapping carries ``_meta.keyframe_order`` and ``_meta.keyframe_count``, the order
hash of the keyframes the documents were built from. The backend compares it with its own
keyframes.json and ignores ASR results from an index whose ids point at other keyframes.
Group N, appended at the end by append_traffic_index.py, keeps every earlier position, so an
index built before that step stays valid.

Incremental by default: data/indexing/es_asr_state.json remembers the keyframe order and a
signature (file count, latest mtime) of every data/asr/<video_id>/ folder, so a rerun only
reads the ASR folders that were added or changed. A full rebuild happens with --full, when
the index or asr_texts.json does not exist yet, or when keyframes.json changed its keyframe
order (FAISS ids shift, so every document id would be stale).
"""

import argparse
import json
import logging
import sys
from pathlib import Path

from elasticsearch import Elasticsearch, helpers

from _common import keyframe_order_hash as _order_hash
from _common import setup_logging, write_json_atomic

logger = logging.getLogger(__name__)

INDEX_NAME = "keyframes_metadata"
ASR_TEXTS_FILENAME = "asr_texts.json"
STATE_VERSION = 2
MAPPINGS = {
    "properties": {
        "faiss_id": {"type": "integer"},
        "asr_text": {"type": "text"},
    }
}


def keyframe_order_hash(keyframes: list[dict]) -> str:
    return _order_hash([keyframe["keyframe_id"] for keyframe in keyframes])


def folder_signature(video_dir: Path) -> list[int]:
    """[file count, latest mtime_ns]: changes when shot files are added, removed or rewritten."""
    mtimes = [f.stat().st_mtime_ns for f in video_dir.glob("*.json")]
    return [len(mtimes), max(mtimes, default=0)]


def read_video_texts(video_dir: Path) -> dict[str, str]:
    """segment_id -> ASR text of one video folder."""
    texts = {}
    for asr_file in video_dir.glob("*.json"):
        segment_id = f"{video_dir.name}_{asr_file.stem}"  # e.g. L21_V001_S00006
        try:
            with open(asr_file, encoding="utf-8") as f:
                text = json.load(f).get("text", "").strip()
        except (OSError, ValueError, AttributeError) as e:
            logger.error("Failed to read %s: %s", asr_file, e)
            continue
        if text:
            texts[segment_id] = text
    return texts


def load_state(state_path: Path) -> dict:
    if not state_path.exists():
        return {}
    try:
        with open(state_path, encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, ValueError) as e:
        logger.warning("Ignoring unreadable state %s: %s", state_path, e)
        return {}
    return state if state.get("version") == STATE_VERSION else {}


def load_asr_texts(path: Path) -> dict[str, dict[str, str]]:
    """video_id -> segment_id -> text written by a previous run (empty when absent)."""
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        logger.warning("Ignoring unreadable %s: %s", path, e)
        return {}
    return data.get("videos", {}) if data.get("version") == 1 else {}


def build_es_index(
    data_root: Path, es_url: str, full: bool = False, index_name: str = INDEX_NAME
) -> bool:
    """Returns False when the index could not be (fully) built."""
    keyframes_path = data_root / "keyframes.json"
    asr_dir = data_root / "asr"
    asr_texts_path = data_root / ASR_TEXTS_FILENAME
    state_path = data_root / "indexing" / "es_asr_state.json"

    if not keyframes_path.exists():
        logger.error("keyframes.json not found at %s", keyframes_path)
        return False

    logger.info("Connecting to Elasticsearch at %s...", es_url)
    es = Elasticsearch(es_url)
    if not es.ping():
        logger.error("Could not connect to Elasticsearch. Is it running? (docker compose up -d)")
        return False

    logger.info("Loading keyframes manifest...")
    with open(keyframes_path, encoding="utf-8") as f:
        keyframes = json.load(f).get("keyframes", [])
    order_hash = keyframe_order_hash(keyframes)

    state = {} if full else load_state(state_path)
    if not es.indices.exists(index=index_name):
        state = {}
    if state and state.get("keyframe_order") != order_hash:
        logger.info("keyframes.json order changed since the last build, rebuilding everything")
        state = {}
    if state and not asr_texts_path.exists():
        logger.info("%s is missing, rebuilding everything", ASR_TEXTS_FILENAME)
        state = {}
    full = not state
    old_texts = {} if full else load_asr_texts(asr_texts_path)
    old_folders: dict[str, list[int]] = state.get("folders", {})

    # Which ASR folders need to be (re)read
    folders: dict[str, list[int]] = {}
    changed: list[Path] = []
    if asr_dir.exists():
        for video_dir in sorted(p for p in asr_dir.iterdir() if p.is_dir()):
            signature = folder_signature(video_dir)
            folders[video_dir.name] = signature
            if full or old_folders.get(video_dir.name) != signature:
                changed.append(video_dir)
    removed = sorted(set(old_folders) - set(folders))
    touched_videos = {d.name for d in changed} | set(removed)

    logger.info(
        "%s build: %d ASR folders, %d to read, %d removed",
        "Full" if full else "Incremental",
        len(folders),
        len(changed),
        len(removed),
    )
    if not full and not touched_videos:
        logger.info("Nothing changed, Elasticsearch index is up to date.")
        return True

    texts = {video: texts for video, texts in old_texts.items() if video not in touched_videos}
    for video_dir in changed:
        video_texts = read_video_texts(video_dir)
        if video_texts:
            texts[video_dir.name] = video_texts
    logger.info("Found ASR texts for %d segments.", sum(len(t) for t in texts.values()))

    # Index keyframes of the touched videos; delete documents whose text disappeared
    actions = []
    updated = deleted = 0
    for idx, keyframe in enumerate(keyframes):
        video_id = keyframe["video_id"]
        if not full and video_id not in touched_videos:
            continue
        segment_id = keyframe.get("segment_id") or ""
        text = texts.get(video_id, {}).get(segment_id)
        if text:
            actions.append(
                {
                    "_index": index_name,
                    "_id": str(idx),
                    "_source": {"faiss_id": idx, "asr_text": text},
                }
            )
            updated += 1
        elif not full and segment_id in old_texts.get(video_id, {}):
            actions.append({"_op_type": "delete", "_index": index_name, "_id": str(idx)})
            deleted += 1
    logger.info("Keyframes with ASR text updated: %d, removed: %d", updated, deleted)

    if full:
        if es.indices.exists(index=index_name):
            es.indices.delete(index=index_name)
        es.indices.create(index=index_name, mappings=MAPPINGS)

    logger.info("Sending %d actions to Elasticsearch...", len(actions))
    # A delete of a document that is already gone is not an error
    _, errors = helpers.bulk(es, actions, raise_on_error=False)
    real_errors = [e for e in errors if e.get("delete", {}).get("status") != 404]
    if real_errors:
        logger.error("%d bulk errors, first: %s", len(real_errors), real_errors[0])
        logger.error("State not saved; the next run will retry these folders.")
        return False
    es.indices.refresh(index=index_name)
    # The backend compares this with its keyframes.json before trusting the document ids
    es.indices.put_mapping(
        index=index_name,
        meta={"keyframe_order": order_hash, "keyframe_count": len(keyframes)},
    )

    write_json_atomic(asr_texts_path, {"version": 1, "videos": texts}, indent=1)
    write_json_atomic(
        state_path,
        {"version": STATE_VERSION, "keyframe_order": order_hash, "folders": folders},
        indent=1,
    )
    logger.info("Saved transcripts to %s; restart the backend to load them.", asr_texts_path)
    logger.info("Done building Elasticsearch index!")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--es-url", default="http://localhost:9200")
    parser.add_argument("--index-name", default=INDEX_NAME, help="must match AIC_ES_INDEX_NAME")
    parser.add_argument("--full", action="store_true", help="Rebuild everything from scratch")
    args = parser.parse_args()
    setup_logging()
    return 0 if build_es_index(args.data_root, args.es_url, args.full, args.index_name) else 1


if __name__ == "__main__":
    sys.exit(main())
