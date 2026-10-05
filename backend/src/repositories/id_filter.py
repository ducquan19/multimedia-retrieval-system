"""Helpers for restricting a search to a subset of FAISS ids (positions in keyframes.json).

A restriction is a boolean mask with one entry per keyframe: True = the keyframe may be returned.
"""

import numpy as np


def mask_from_ids(size: int, ids: np.ndarray) -> np.ndarray:
    mask = np.zeros(size, dtype=bool)
    mask[ids] = True
    return mask


def combine(size: int, allowed: np.ndarray | None, excluded_ids: np.ndarray) -> np.ndarray | None:
    """Allowed mask minus the excluded ids; None when nothing is restricted."""
    if allowed is None and excluded_ids.size == 0:
        return None
    mask = np.ones(size, dtype=bool) if allowed is None else allowed.copy()
    mask[excluded_ids] = False
    return mask


def mask_to_ranges(mask: np.ndarray) -> list[tuple[int, int]]:
    """Inclusive [start, end] runs of True values, e.g. [F, T, T, F, T] -> [(1, 2), (4, 4)]."""
    padded = np.concatenate(([False], mask, [False])).astype(np.int8)
    edges = np.flatnonzero(np.diff(padded))
    return [(int(start), int(end) - 1) for start, end in zip(edges[::2], edges[1::2], strict=True)]
