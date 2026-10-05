"""Offline retrieval evaluation against a running backend: Recall@K and MRR.

Use it before and after changing fusion weights, TRAKE parameters, models or indexes, so a
change is kept only when the numbers improve.

Ground truth: a JSONL file, one labelled query per line, e.g.
    {"id": "kis-01", "query_type": "KIS", "query": "người đàn ông mặc áo đỏ ...",
     "targets": [{"video_id": "L21_V001", "frame_start": 1200, "frame_end": 1450}]}
    {"id": "trake-01", "query_type": "TRAKE",
     "events": ["giậm nhảy", "bay qua xà", "tiếp đất"],
     "targets": [{"video_id": "L23_V004"}]}
    {"id": "kis-02", "query_type": "KIS", "query": "...", "targets": [{"video_id": "M01_V010"}],
     "request": {"model_choices": ["siglip", "beit3"],
                 "search_sources": {"image": true, "asr": true}}}

A single-frame result is a hit when its video matches and, if frame_start/frame_end are
given, its frame_id lies in that range. A TRAKE result is a hit when its video matches (and,
with ranges, every event frame lies in the range). "request" overrides the search payload.

Example:
    python scripts/evaluate_retrieval.py data/eval/queries.jsonl --top-k 100 \\
        --api http://localhost:8000 --output eval_results.json
"""

import argparse
import json
import statistics
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

CUTOFFS = (1, 5, 10, 20, 50, 100)


def build_payload(item: dict[str, Any], top_k: int) -> dict[str, Any]:
    query_type = item["query_type"]
    payload: dict[str, Any] = {"query_type": query_type, "top_k": top_k}
    if query_type == "TRAKE":
        payload["main_query"] = item.get("main_query")
        payload["events"] = [
            {"event_index": index, "query": query}
            for index, query in enumerate(item["events"], start=1)
        ]
    else:
        payload["query"] = item["query"]
    payload.update(item.get("request", {}))
    return payload


def in_target(video_id: str, frames: list[int], target: dict[str, Any]) -> bool:
    if video_id != target["video_id"]:
        return False
    start = target.get("frame_start")
    end = target.get("frame_end")
    return all(
        (start is None or frame >= start) and (end is None or frame <= end) for frame in frames
    )


def first_hit_rank(response: dict[str, Any], targets: list[dict[str, Any]]) -> int | None:
    for result in response["results"]:
        if "events" in result:
            frames = [event["frame_id"] for event in result["events"]]
        else:
            frames = [result["frame_id"]]
        if any(in_target(result["video_id"], frames, target) for target in targets):
            return result["rank"]
    return None


def search(api: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{api.rstrip('/')}/api/search",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def summarize(ranks: list[int | None], top_k: int) -> dict[str, float]:
    count = len(ranks)
    summary = {
        f"recall@{k}": sum(1 for r in ranks if r is not None and r <= k) / count
        for k in CUTOFFS
        if k <= top_k
    }
    summary["mrr"] = sum(1 / r for r in ranks if r is not None) / count
    found = [r for r in ranks if r is not None]
    summary["median_rank_when_found"] = statistics.median(found) if found else float("nan")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("queries", type=Path, help="ground-truth JSONL")
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--top-k", type=int, default=100)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--output", type=Path, help="write per-query ranks and the summary")
    args = parser.parse_args()

    items = [
        json.loads(line)
        for line in args.queries.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not items:
        print(f"No queries in {args.queries}", file=sys.stderr)
        return 1

    rows = []
    for item in items:
        try:
            response = search(args.api, build_payload(item, args.top_k), args.timeout)
        except (urllib.error.URLError, TimeoutError) as exc:
            print(f"[ERROR] {item.get('id')}: {exc}", file=sys.stderr)
            return 1
        rank = first_hit_rank(response, item["targets"])
        rows.append({"id": item.get("id"), "query_type": item["query_type"], "rank": rank})
        print(f"{item.get('id', '?'):<20} {item['query_type']:<8} rank={rank}")

    report: dict[str, Any] = {"overall": summarize([r["rank"] for r in rows], args.top_k)}
    for query_type in sorted({r["query_type"] for r in rows}):
        ranks = [r["rank"] for r in rows if r["query_type"] == query_type]
        report[query_type] = summarize(ranks, args.top_k)

    print()
    for group, metrics in report.items():
        formatted = "  ".join(f"{name}={value:.3f}" for name, value in metrics.items())
        count = sum(1 for r in rows if group in ("overall", r["query_type"]))
        print(f"{group:<8} n={count}  {formatted}")
    if args.output:
        args.output.write_text(
            json.dumps({"summary": report, "queries": rows}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
