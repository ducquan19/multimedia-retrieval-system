"""Helpers shared by the preprocessing scripts (run them as ``python scripts/<x>.py``)."""

import argparse
import hashlib
import json
import logging
import shutil
from collections.abc import Callable, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp"})


def setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )


def keyframe_order_hash(keyframe_ids: Sequence[str]) -> str:
    """SHA-1 of the keyframe_id order of keyframes.json (= the FAISS id order).

    Must stay identical to backend/src/repositories/keyframe_metadata_repository.py.
    """
    digest = hashlib.sha1()
    for keyframe_id in keyframe_ids:
        digest.update(keyframe_id.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def write_index_meta(
    index_path: Path, *, ntotal: int, dim: int, keyframe_ids: Sequence[str]
) -> Path:
    """Write <index>.meta.json; the backend refuses an index whose keyframe order differs."""
    meta_path = index_path.with_name(index_path.name + ".meta.json")
    meta_path.write_text(
        json.dumps(
            {
                "version": 1,
                "ntotal": ntotal,
                "dim": dim,
                "keyframe_count": len(keyframe_ids),
                "keyframe_order": keyframe_order_hash(keyframe_ids),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return meta_path


def shard_arg(value: str) -> tuple[int, int]:
    """argparse type for --shard K/N (1-based: 1/4 ... 4/4)."""
    try:
        index_text, count_text = value.split("/")
        index, count = int(index_text), int(count_text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("use K/N, e.g. 1/4") from exc
    if not 1 <= index <= count:
        raise argparse.ArgumentTypeError("K must be between 1 and N")
    return index, count


def add_shard_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--shard",
        type=shard_arg,
        default=(1, 1),
        metavar="K/N",
        help="process only part K of N (split the work across several machines), e.g. 2/4",
    )


def select_shard[T](
    items: Sequence[T], shard: tuple[int, int], weight: Callable[[T], float] | None = None
) -> list[T]:
    """Deterministic part ``shard`` of ``items`` (sorted first, so every machine agrees).

    Without ``weight``: contiguous chunks. With ``weight``: greedy balancing (heaviest item to
    the lightest shard), e.g. by video file size.
    """
    index, count = shard
    ordered = sorted(items)  # type: ignore[type-var]
    if count == 1:
        return list(ordered)
    if weight is None:
        size = -(-len(ordered) // count)
        return list(ordered[(index - 1) * size : index * size])
    shards: list[list[T]] = [[] for _ in range(count)]
    totals = [0.0] * count
    for item in sorted(ordered, key=weight, reverse=True):
        lightest = totals.index(min(totals))
        shards[lightest].append(item)
        totals[lightest] += weight(item)
    return sorted(shards[index - 1])  # type: ignore[type-var]


def make_archive(directory: Path, archive_base: Path, fmt: str = "gztar") -> Path:
    """Compress ``directory`` (e.g. to download results from Kaggle)."""
    archive = shutil.make_archive(
        str(archive_base), fmt, root_dir=str(directory.parent), base_dir=directory.name
    )
    return Path(archive)


def matches_any(video_id: str, selectors: Sequence[str] | None) -> bool:
    """True when no selector is given or video_id equals / starts with one of them."""
    return not selectors or any(video_id == s or video_id.startswith(s) for s in selectors)
