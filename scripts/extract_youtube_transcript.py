"""
Lấy transcript (phụ đề) YouTube cho các video M/S và lưu theo từng shot,
cùng định dạng với thư mục data/asr:

    <output_dir>/<video_id>/S00000.json
    {
        "video_id": "M01_V001",
        "scene_id": 0,
        "start_time_s": 0.0,
        "end_time_s": 0.92,
        "text": "...",
        "segments": [{"start": .., "end": .., "text": "..", "overlap": ..}]
    }

Thông tin shot lấy từ data/scenes/<video_id>.scenes.csv,
YouTube URL lấy từ trường "watch_url" trong metadata JSON.

Có 2 cách lấy phụ đề (--source):
- api:   youtube-transcript-api, nhanh nhưng không có cookie nên dễ bị YouTube chặn IP
         (IpBlocked) dù video vẫn xem được trên trình duyệt.
- ytdlp: yt-dlp, dùng cookie trình duyệt (--cookies-from-browser / --cookies) để
         YouTube coi như người dùng đã đăng nhập.
- auto (mặc định): dùng api, khi bị chặn IP thì chuyển hẳn sang ytdlp.

Cài đặt:
    pip install "youtube-transcript-api>=1.0" yt-dlp tqdm

Trạng thái được lưu ở <output_dir>/_youtube_transcript_state.json: video đã lấy
transcript hoặc không có transcript sẽ được bỏ qua ở các lần chạy sau
(dùng --overwrite / --retry-missing để chạy lại).

Ví dụ:
    python scripts/extract_youtube_transcript.py
    python scripts/extract_youtube_transcript.py --prefix M01 --prefix S01 --overwrite
    python scripts/extract_youtube_transcript.py --proxy http://user:pass@host:port
    python scripts/extract_youtube_transcript.py --cookies-from-browser firefox
    python scripts/extract_youtube_transcript.py --source ytdlp --cookies cookies.txt
"""

import argparse
import csv
import json
import random
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from tqdm import tqdm
from youtube_transcript_api import (
    IpBlocked,
    NoTranscriptFound,
    RequestBlocked,
    TranscriptsDisabled,
    VideoUnavailable,
    YouTubeTranscriptApi,
)
from youtube_transcript_api.proxies import GenericProxyConfig

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_METADATA_DIR = ROOT / "data" / "aic26-b2-media-info" / "media-info"
DEFAULT_SCENES_DIR = ROOT / "data" / "scenes"
DEFAULT_OUTPUT_DIR = ROOT / "data" / "asr"

STATE_FILENAME = "_youtube_transcript_state.json"

# Chỉ gán câu nói vào shot nếu giao nhau hơn ngưỡng này (giống notebooks/extract_asr.ipynb)
MIN_OVERLAP_S = 0.1


def parse_youtube_id(url):
    """Lấy YouTube video id từ watch_url (hỗ trợ watch?v=, youtu.be/, shorts/)."""
    parsed = urlparse(url)
    if parsed.hostname and parsed.hostname.endswith("youtu.be"):
        return parsed.path.lstrip("/").split("/")[0] or None
    query_id = parse_qs(parsed.query).get("v")
    if query_id:
        return query_id[0]
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) >= 2 and parts[0] in ("shorts", "embed", "live"):
        return parts[1]
    return None


def fetch_transcript(api, youtube_id, languages):
    """
    Ưu tiên phụ đề thủ công theo `languages`, sau đó phụ đề tự sinh,
    cuối cùng là bất kỳ phụ đề nào có thể dịch sang ngôn ngữ đầu tiên.
    Trả về (list snippet {start, end, text}, language_code, is_generated).
    """
    transcript_list = api.list(youtube_id)
    try:
        transcript = transcript_list.find_manually_created_transcript(languages)
    except NoTranscriptFound:
        try:
            transcript = transcript_list.find_generated_transcript(languages)
        except NoTranscriptFound:
            transcript = next((t for t in transcript_list if t.is_translatable), None)
            if transcript is None:
                raise
            transcript = transcript.translate(languages[0])

    fetched = transcript.fetch()
    snippets = [
        {
            "start": float(s.start),
            "end": float(s.start) + float(s.duration),
            "text": " ".join(s.text.split()),
        }
        for s in fetched
    ]
    return snippets, transcript.language_code, transcript.is_generated


class NoCaptions(Exception):
    """yt-dlp không tìm thấy phụ đề phù hợp."""


def make_ytdlp(cookies_from_browser=None, cookies=None, proxy=None):
    from yt_dlp import YoutubeDL

    opts = {"skip_download": True, "quiet": True, "no_warnings": True}
    if cookies_from_browser:
        opts["cookiesfrombrowser"] = (cookies_from_browser,)
    if cookies:
        opts["cookiefile"] = str(cookies)
    if proxy:
        opts["proxy"] = proxy
    return YoutubeDL(opts)


def pick_caption(tracks, languages, suffixes):
    for lang in languages:
        for suffix in suffixes:
            formats = tracks.get(f"{lang}{suffix}") or []
            json3 = next((f for f in formats if f.get("ext") == "json3"), None)
            if json3:
                return f"{lang}{suffix}", json3["url"]
    return None, None


def parse_json3(data):
    snippets = []
    for event in data.get("events", []):
        text = " ".join("".join(seg.get("utf8", "") for seg in event.get("segs", [])).split())
        if not text or "tStartMs" not in event:
            continue
        start = event["tStartMs"] / 1000
        snippets.append(
            {
                "start": start,
                "end": start + event.get("dDurationMs", 0) / 1000,
                "text": text,
            }
        )
    return snippets


def fetch_transcript_ytdlp(ydl, youtube_id, languages):
    """Giống fetch_transcript nhưng qua yt-dlp: ưu tiên phụ đề thủ công, rồi tự sinh."""
    from yt_dlp.utils import DownloadError

    try:
        info = ydl.extract_info(f"https://www.youtube.com/watch?v={youtube_id}", download=False)
    except DownloadError as e:
        message = str(e).lower()
        if "video unavailable" in message or "private video" in message:
            raise NoCaptions("VideoUnavailable") from e
        raise

    lang, url = pick_caption(info.get("subtitles") or {}, languages, ("", "-VN"))
    generated = False
    if not url:
        # "-orig" là phụ đề tự sinh gốc; không hậu tố có thể là bản dịch máy
        lang, url = pick_caption(info.get("automatic_captions") or {}, languages, ("-orig", ""))
        generated = True
    if not url:
        raise NoCaptions("NoTranscriptFound")

    with ydl.urlopen(url) as response:
        snippets = parse_json3(json.loads(response.read().decode("utf-8")))
    return snippets, lang, generated


def is_blocked(error):
    """YouTube chặn IP (youtube-transcript-api) hoặc trả 429 (yt-dlp / urllib)."""
    if isinstance(error, (IpBlocked, RequestBlocked)):
        return True
    status = getattr(error, "status", None) or getattr(error, "code", None)
    if status == 429:
        return True
    message = str(error)
    return "429" in message or "confirm you" in message.lower()


def get_overlap(start1, end1, start2, end2):
    return max(0.0, min(end1, end2) - max(start1, start2))


def load_shots(csv_path):
    with open(csv_path, encoding="utf-8", newline="") as f:
        return [
            {
                "video_id": row["video_id"],
                "scene_id": int(row["scene_id"]),
                "start_time_s": float(row["start_time_s"]),
                "end_time_s": float(row["end_time_s"]),
            }
            for row in csv.DictReader(f)
        ]


def map_transcript_to_shots(snippets, shots):
    """Ánh xạ các đoạn transcript vào từng shot dựa trên thời gian giao nhau."""
    shot_results = {
        shot["scene_id"]: {
            **shot,
            "text": "",
            "segments": [],
        }
        for shot in shots
    }

    for snippet in snippets:
        if not snippet["text"]:
            continue
        for shot in shots:
            overlap = get_overlap(
                snippet["start"],
                snippet["end"],
                shot["start_time_s"],
                shot["end_time_s"],
            )
            if overlap <= MIN_OVERLAP_S:
                continue
            result = shot_results[shot["scene_id"]]
            result["segments"].append(
                {
                    "start": round(snippet["start"], 2),
                    "end": round(snippet["end"], 2),
                    "text": snippet["text"],
                    "overlap": round(overlap, 2),
                }
            )
            result["text"] = f"{result['text']} {snippet['text']}".strip()

    return shot_results


def save_shots(shot_results, video_out_dir):
    video_out_dir.mkdir(parents=True, exist_ok=True)
    for scene_id, data in shot_results.items():
        out_path = video_out_dir / f"S{scene_id:05d}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)


def has_all_shots(video_out_dir, shot_count):
    return video_out_dir.is_dir() and len(list(video_out_dir.glob("S*.json"))) >= shot_count


def load_state(state_path):
    """{"done": {video_id: info}, "no_transcript": {video_id: reason}}"""
    state = {"done": {}, "no_transcript": {}}
    if state_path.exists():
        with open(state_path, encoding="utf-8") as f:
            state.update(json.load(f))
    return state


def save_state(state, state_path):
    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = state_path.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)
    tmp_path.replace(state_path)


def collect_videos(metadata_dir, prefixes):
    paths = sorted(metadata_dir.glob("*.json"))
    return [p for p in paths if p.stem.startswith(tuple(prefixes))]


def main():
    parser = argparse.ArgumentParser(description="Lấy transcript YouTube và lưu theo shot")
    parser.add_argument("--metadata-dir", type=Path, default=DEFAULT_METADATA_DIR)
    parser.add_argument("--scenes-dir", type=Path, default=DEFAULT_SCENES_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--prefix",
        action="append",
        help="Tiền tố video_id cần xử lý (lặp lại được). Mặc định: M, S",
    )
    parser.add_argument(
        "--languages",
        nargs="+",
        default=["vi"],
        help="Thứ tự ngôn ngữ ưu tiên (mặc định: vi)",
    )
    parser.add_argument("--overwrite", action="store_true", help="Ghi đè kết quả đã có")
    parser.add_argument(
        "--retry-missing",
        action="store_true",
        help="Thử lại các video lần trước không có transcript",
    )
    parser.add_argument(
        "--delay", type=float, default=3.0, help="Nghỉ giữa các video (giây, cộng thêm ngẫu nhiên)"
    )
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument(
        "--pause-every",
        type=int,
        default=30,
        help="Nghỉ dài sau mỗi N video lấy được transcript (0 = tắt)",
    )
    parser.add_argument("--pause", type=float, default=120, help="Thời gian nghỉ dài (giây)")
    parser.add_argument(
        "--cooldown",
        type=float,
        default=900,
        help="Nghỉ khi bị chặn IP / 429 (giây), gấp đôi sau mỗi lần bị chặn liên tiếp",
    )
    parser.add_argument(
        "--max-blocks",
        type=int,
        default=3,
        help="Số lần nghỉ khi bị chặn liên tiếp trước khi dừng hẳn",
    )
    parser.add_argument("--proxy", help="Proxy http(s) nếu bị YouTube chặn IP")
    parser.add_argument(
        "--source",
        choices=["auto", "api", "ytdlp"],
        default="auto",
        help="auto: dùng api, bị chặn IP thì chuyển sang yt-dlp",
    )
    parser.add_argument(
        "--cookies-from-browser",
        metavar="BROWSER",
        help="Lấy cookie YouTube từ trình duyệt cho yt-dlp (firefox, edge, chrome, ...)",
    )
    parser.add_argument(
        "--cookies", type=Path, help="File cookies.txt (định dạng Netscape) cho yt-dlp"
    )
    args = parser.parse_args()

    proxy_config = (
        GenericProxyConfig(http_url=args.proxy, https_url=args.proxy) if args.proxy else None
    )
    api = YouTubeTranscriptApi(proxy_config=proxy_config)
    ydl = None
    use_ytdlp = args.source == "ytdlp"
    if args.source != "api" and not (args.cookies_from_browser or args.cookies):
        print("Gợi ý: thêm --cookies-from-browser firefox để yt-dlp ít bị chặn hơn")

    videos = collect_videos(args.metadata_dir, args.prefix or ["M", "S"])
    print(f"Tìm thấy {len(videos)} video metadata")

    state_path = args.output_dir / STATE_FILENAME
    state = load_state(state_path)

    missing_scenes, no_transcript, failed = [], [], []
    done, skipped, skipped_missing = 0, 0, 0
    consecutive_blocks, stopped = 0, False

    for meta_path in tqdm(videos, desc="Transcripts"):
        video_id = meta_path.stem
        video_out_dir = args.output_dir / video_id

        # Bỏ qua video đã lấy transcript / đã biết là không có transcript
        if not args.overwrite:
            if video_id in state["done"] and video_out_dir.is_dir():
                skipped += 1
                continue
            if video_id in state["no_transcript"] and not args.retry_missing:
                skipped_missing += 1
                continue

        csv_path = args.scenes_dir / f"{video_id}.scenes.csv"
        if not csv_path.exists():
            missing_scenes.append(video_id)
            continue

        shots = load_shots(csv_path)
        # Kết quả có sẵn từ trước khi có file trạng thái
        if not args.overwrite and has_all_shots(video_out_dir, len(shots)):
            state["done"].setdefault(video_id, {"shots": len(shots)})
            save_state(state, state_path)
            skipped += 1
            continue

        with open(meta_path, encoding="utf-8") as f:
            metadata = json.load(f)
        youtube_id = parse_youtube_id(metadata.get("watch_url", ""))
        if not youtube_id:
            failed.append((video_id, "không đọc được watch_url"))
            continue

        snippets = None
        attempt = 0
        while attempt < args.retries:
            attempt += 1
            try:
                if use_ytdlp:
                    if ydl is None:
                        ydl = make_ytdlp(args.cookies_from_browser, args.cookies, args.proxy)
                    snippets, lang, generated = fetch_transcript_ytdlp(
                        ydl, youtube_id, args.languages
                    )
                else:
                    snippets, lang, generated = fetch_transcript(api, youtube_id, args.languages)
                consecutive_blocks = 0
                break
            except (TranscriptsDisabled, NoTranscriptFound, VideoUnavailable, NoCaptions) as e:
                reason = str(e) if isinstance(e, NoCaptions) else type(e).__name__
                no_transcript.append((video_id, reason))
                state["no_transcript"][video_id] = reason
                save_state(state, state_path)
                consecutive_blocks = 0
                break
            except Exception as e:  # noqa: BLE001 - phân loại lỗi bằng is_blocked()
                if not is_blocked(e):  # lỗi mạng tạm thời
                    if attempt == args.retries:
                        failed.append((video_id, f"{type(e).__name__}: {str(e).splitlines()[0]}"))
                    else:
                        time.sleep(args.delay * 2**attempt + random.random())
                    continue

                # Bị chặn IP / 429: thử lại ngay chỉ làm lệnh chặn kéo dài hơn
                if args.source == "auto" and not use_ytdlp:
                    tqdm.write("youtube-transcript-api bị chặn IP, chuyển sang yt-dlp")
                    use_ytdlp = True
                    attempt = 0
                    continue
                consecutive_blocks += 1
                if consecutive_blocks > args.max_blocks:
                    failed.append((video_id, f"{type(e).__name__}: {str(e).splitlines()[0]}"))
                    stopped = True
                    break
                wait = args.cooldown * 2 ** (consecutive_blocks - 1)
                tqdm.write(
                    f"{video_id}: bị YouTube chặn ({type(e).__name__}), nghỉ {wait / 60:.0f} phút "
                    f"rồi thử lại (lần {consecutive_blocks}/{args.max_blocks})"
                )
                time.sleep(wait)
                attempt = 0

        if stopped:
            tqdm.write(
                f"Vẫn bị chặn sau {args.max_blocks} lần nghỉ, dừng lại. "
                "Hãy đổi mạng / dùng cookie hoặc proxy rồi chạy lại (video đã xong sẽ được bỏ qua)."
            )
            break
        if snippets is None:
            continue

        # Vẫn lưu đủ shot (text rỗng) để cấu trúc giống data/asr
        save_shots(map_transcript_to_shots(snippets, shots), video_out_dir)
        # Chỉ đánh dấu hoàn thành sau khi đã ghi đủ các shot
        state["no_transcript"].pop(video_id, None)
        state["done"][video_id] = {
            "youtube_id": youtube_id,
            "language": lang,
            "generated": generated,
            "snippets": len(snippets),
            "shots": len(shots),
        }
        save_state(state, state_path)
        done += 1
        tqdm.write(
            f"{video_id}: {len(snippets)} đoạn ({lang}, {'auto' if generated else 'manual'})"
        )
        if args.pause_every and done % args.pause_every == 0:
            tqdm.write(f"Đã lấy {done} video, nghỉ {args.pause:.0f} giây để tránh bị chặn")
            time.sleep(args.pause)
        else:
            time.sleep(args.delay * random.uniform(1, 2))

    print("-" * 40)
    print(
        f"Hoàn thành: {done} | Đã có sẵn (bỏ qua): {skipped} | "
        f"Không có transcript từ lần trước (bỏ qua): {skipped_missing}"
    )
    if missing_scenes:
        print(f"Thiếu file scenes ({len(missing_scenes)}): {', '.join(missing_scenes)}")
    if no_transcript:
        print(f"Không có transcript ({len(no_transcript)}):")
        for video_id, reason in no_transcript:
            print(f"  {video_id}: {reason}")
    if failed:
        print(f"Lỗi ({len(failed)}):")
        for video_id, reason in failed:
            print(f"  {video_id}: {reason}")


if __name__ == "__main__":
    main()
