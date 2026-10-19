"""Helpers of scripts/_common.py that the data pipeline relies on."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from _common import atomic_path, write_json_atomic  # noqa: E402


def test_write_json_atomic_replaces_the_file(tmp_path: Path) -> None:
    path = tmp_path / "keyframes.json"
    path.write_text('{"version": 0}', encoding="utf-8")

    write_json_atomic(path, {"version": 1, "text": "tiếng Việt"}, indent=2)

    assert json.loads(path.read_text(encoding="utf-8")) == {"version": 1, "text": "tiếng Việt"}
    assert list(tmp_path.iterdir()) == [path]


def test_interrupted_write_keeps_the_previous_file(tmp_path: Path) -> None:
    path = tmp_path / "keyframes.json"
    path.write_text('{"version": 1}', encoding="utf-8")

    with pytest.raises(KeyboardInterrupt), atomic_path(path) as tmp:
        tmp.write_text('{"vers', encoding="utf-8")
        raise KeyboardInterrupt

    assert path.read_text(encoding="utf-8") == '{"version": 1}'
    assert list(tmp_path.iterdir()) == [path]
