"""
Lấy transcript ASR cho video batch 2 (M, S) từ phụ đề YouTube thay vì chạy Whisper.

Hai bước:
  fetch  — tải phụ đề cho mỗi video trong media-info/*.json, lưu thô ở
           data/asr_youtube/<video_id>.json. Video đã có file sẽ được bỏ qua,
           video lỗi ghi vào data/asr_youtube/_failed.csv (cần chạy Whisper bù).
  align  — gán các đoạn phụ đề vào shot TransNetV2 (transnetv2_results_batch2),
           ghi ra data/asr/<video_id>/S<scene_id:05d>.json cùng schema batch 1.
           Video chưa có shot (S01) dùng cửa sổ keyframe BTC
           [pts_time(n), pts_time(n+1)) và ghi ra <nnnn>.json (khớp tên ảnh).

Lưu ý: media-info của video S01 bị BTC đặt tên S01_V0xx.json, trong khi video và
keyframe là S01-V0xx; video_id được chuẩn hoá về S01-V0xx.

Yêu cầu: pip install youtube-transcript-api
"""

import argparse
import csv
import json
import logging
import random
import re
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
PREFERRED_LANGUAGE = "vi"


def normalize_video_id(stem: str) -> str:
    # S01_V001 -> S01-V001 (tên media-info của S bị nhầm dấu gạch)
    if stem.startswith("S"):
        return stem.replace("_", "-", 1)
    return stem


def youtube_id(watch_url: str) -> str:
    match = re.search(r"(?:v=|youtu\.be/)([\w-]{11})", watch_url)
    if not match:
        raise ValueError(f"Cannot parse YouTube id from {watch_url}")
    return match.group(1)


def pick_transcript(transcript_list):
    """Ưu tiên phụ đề tiếng Việt (tự sinh hoặc thủ công).

    Một số video có thêm track tiếng Anh do YouTube lồng tiếng tự động,
    track đó không phải lời gốc nên chỉ dùng khi không có tiếng Việt.
    """
    transcripts = list(transcript_list)
    for t in transcripts:
        if t.language_code.split("-")[0] == PREFERRED_LANGUAGE:
            return t, transcripts
    return transcripts[0], transcripts


def fetch(media_info_dir: Path, out_dir: Path, sleep_s: float, retries: int, proxy: str | None):
    from youtube_transcript_api import IpBlocked, RequestBlocked, YouTubeTranscriptApi
    from youtube_transcript_api.proxies import GenericProxyConfig

    proxy_config = GenericProxyConfig(http_url=proxy, https_url=proxy) if proxy else None
    api = YouTubeTranscriptApi(proxy_config=proxy_config)
    out_dir.mkdir(parents=True, exist_ok=True)
    failed = []
    blocked = False

    files = sorted(media_info_dir.glob("*.json"))
    for i, info_path in enumerate(files, 1):
        video_id = normalize_video_id(info_path.stem)
        out_path = out_dir / f"{video_id}.json"
        if out_path.exists():
            continue

        info = json.loads(info_path.read_text(encoding="utf-8"))
        yt_id = youtube_id(info["watch_url"])

        for attempt in range(1, retries + 1):
            try:
                chosen, available = pick_transcript(api.list(yt_id))
                fetched = chosen.fetch()
                break
            except (IpBlocked, RequestBlocked):
                # YouTube chặn IP: thử tiếp chỉ làm lệnh chặn kéo dài. Dừng hẳn,
                # chạy lại sau (video đã tải sẽ được bỏ qua) hoặc dùng --proxy.
                blocked = True
                break
            except Exception as e:  # noqa: BLE001 - lỗi mạng / không có phụ đề
                error = f"{type(e).__name__}: {str(e).splitlines()[0][:200]}"
                logger.warning("[%d/%d] %s attempt %d failed: %s", i, len(files), video_id, attempt, error)
                time.sleep(sleep_s * 2**attempt)
        else:
            failed.append({"video_id": video_id, "youtube_id": yt_id, "error": error})
            continue
        if blocked:
            logger.error("[%d/%d] %s: IP blocked by YouTube, stopping. Re-run later or use --proxy.", i, len(files), video_id)
            break

        data = {
            "video_id": video_id,
            "youtube_id": yt_id,
            "youtube_length_s": info.get("length"),
            "language_code": chosen.language_code,
            "is_generated": chosen.is_generated,
            "available": [
                {"language_code": t.language_code, "is_generated": t.is_generated}
                for t in available
            ],
            "snippets": [
                {"start": round(s.start, 3), "duration": round(s.duration, 3), "text": s.text.strip()}
                for s in fetched.snippets
            ],
        }
        out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("[%d/%d] %s: %d snippets (%s)", i, len(files), video_id, len(data["snippets"]), chosen.language_code)
        time.sleep(sleep_s * random.uniform(0.7, 1.3))

    failed_path = out_dir / "_failed.csv"
    with open(failed_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["video_id", "youtube_id", "error"])
        writer.writeheader()
        writer.writerows(failed)
    done = sum(1 for p in out_dir.glob("*.json"))
    logger.info("%s. %d/%d fetched, %d failed (see %s)",
                "Blocked" if blocked else "Done", done, len(files), len(failed), failed_path)


def snippet_intervals(snippets):
    """Phụ đề tự sinh gối lên nhau: cắt end của mỗi đoạn tại start của đoạn kế."""
    intervals = []
    for k, s in enumerate(snippets):
        if not s["text"]:
            continue
        end = s["start"] + s["duration"]
        if k + 1 < len(snippets):
            end = min(end, snippets[k + 1]["start"])
        intervals.append((s["start"], max(end, s["start"]), s["text"]))
    return intervals


def shot_windows(scenes_path: Path):
    """Shot TransNetV2 -> (file stem, id fields, start, end), cùng schema ASR batch 1."""
    with open(scenes_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return [
        (f"S{int(r['scene_id']):05d}", {"scene_id": int(r["scene_id"])},
         float(r["start_time_s"]), float(r["end_time_s"]))
        for r in rows
    ]


def keyframe_windows(map_path: Path, video_end: float):
    """Fallback khi chưa có shot: cửa sổ [pts_time(n), pts_time(n+1)) của keyframe BTC."""
    with open(map_path, encoding="utf-8") as f:
        keyframes = sorted((int(r["n"]), float(r["pts_time"])) for r in csv.DictReader(f))
    return [
        (f"{n:04d}", {"keyframe_n": n}, start,
         keyframes[k + 1][1] if k + 1 < len(keyframes) else max(video_end, start))
        for k, (n, start) in enumerate(keyframes)
    ]


def align(raw_dir: Path, scenes_dir: Path, map_dir: Path, out_dir: Path, offset_s: float):
    raw_files = sorted(p for p in raw_dir.glob("*.json") if not p.name.startswith("_"))
    for raw_path in raw_files:
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        video_id = raw["video_id"]

        intervals = [
            (start + offset_s, end + offset_s, text)
            for start, end, text in snippet_intervals(raw["snippets"])
        ]

        scenes_path = scenes_dir / f"{video_id}.scenes.csv"
        map_path = map_dir / f"{video_id}.csv"
        if scenes_path.exists():
            unit, windows = "shots", shot_windows(scenes_path)
        elif map_path.exists():
            video_end = max([end for _, end, _ in intervals], default=0.0)
            unit, windows = "keyframes", keyframe_windows(map_path, video_end)
        else:
            logger.warning("%s: no TransNetV2 scenes or map-keyframes, skipped", video_id)
            continue

        video_out = out_dir / video_id
        video_out.mkdir(parents=True, exist_ok=True)
        with_text = 0
        for stem, id_fields, start, end in windows:
            segments = [
                {"start": round(s, 3), "end": round(e, 3), "text": t}
                for s, e, t in intervals
                if s < end and e > start
            ]
            text = " ".join(seg["text"] for seg in segments)
            with_text += bool(text)
            record = {
                "video_id": video_id,
                **id_fields,
                "start_time_s": round(start, 6),
                "end_time_s": round(end, 6),
                "text": text,
                "segments": segments,
                "source": f"youtube:{raw['language_code']}",
            }
            (video_out / f"{stem}.json").write_text(
                json.dumps(record, ensure_ascii=False, indent=4), encoding="utf-8"
            )
        logger.info("%s: %d/%d %s with text", video_id, with_text, len(windows), unit)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_fetch = sub.add_parser("fetch", help="Download YouTube transcripts")
    p_fetch.add_argument("--media-info-dir", type=Path, default=ROOT / "data/aic26-b2-media-info/media-info")
    p_fetch.add_argument("--out-dir", type=Path, default=ROOT / "data/asr_youtube")
    p_fetch.add_argument("--sleep", type=float, default=10.0, help="Seconds between videos (jittered)")
    p_fetch.add_argument("--retries", type=int, default=3)
    p_fetch.add_argument("--proxy", help="HTTP(S) proxy URL, e.g. http://user:pass@host:port")

    p_align = sub.add_parser("align", help="Align transcripts to TransNetV2 shots (fallback: BTC keyframes)")
    p_align.add_argument("--raw-dir", type=Path, default=ROOT / "data/asr_youtube")
    p_align.add_argument("--scenes-dir", type=Path, default=ROOT / "data/transnetv2_results_batch2/scenes")
    p_align.add_argument("--map-dir", type=Path, default=ROOT / "data/aic26-b2-map-keyframes/map-keyframes")
    p_align.add_argument("--out-dir", type=Path, default=ROOT / "data/asr")
    p_align.add_argument("--offset", type=float, default=0.0, help="Seconds added to YouTube timestamps")

    args = parser.parse_args()
    if args.command == "fetch":
        fetch(args.media_info_dir, args.out_dir, args.sleep, args.retries, args.proxy)
    else:
        align(args.raw_dir, args.scenes_dir, args.map_dir, args.out_dir, args.offset)
