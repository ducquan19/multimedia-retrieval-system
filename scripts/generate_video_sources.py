import argparse
import json
from pathlib import Path
from typing import Any


def generate_video_sources(
    metadata_path: Path,
    manifest_path: Path,
    output_path: Path,
) -> int:
    metadata: dict[str, dict[str, Any]] = json.loads(
        metadata_path.read_text(encoding="utf-8")
    )
    manifest: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    video_ids = sorted({keyframe["video_id"] for keyframe in manifest["keyframes"]})

    videos: dict[str, dict[str, str | float]] = {}
    missing: list[str] = []
    for video_id in video_ids:
        source = metadata.get(video_id)
        if source is None:
            missing.append(video_id)
            continue

        remote_url = source.get("path")
        fps = source.get("fps")
        if not isinstance(remote_url, str) or not remote_url.startswith(("http://", "https://")):
            raise ValueError(f"{video_id} has an invalid remote video URL")
        if not isinstance(fps, int | float) or isinstance(fps, bool) or fps <= 0:
            raise ValueError(f"{video_id} has an invalid fps value")

        videos[video_id] = {
            "remote_url": remote_url,
            "fps": float(fps),
        }

    if missing:
        raise ValueError(f"Missing metadata for {len(missing)} videos: {', '.join(missing[:5])}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps({"version": 1, "videos": videos}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return len(videos)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create compact video playback metadata without shot boundaries."
    )
    parser.add_argument("--metadata", type=Path, default=Path("data/metadata.json"))
    parser.add_argument("--manifest", type=Path, default=Path("data/keyframes.json"))
    parser.add_argument("--output", type=Path, default=Path("data/video_sources.json"))
    args = parser.parse_args()

    count = generate_video_sources(args.metadata, args.manifest, args.output)
    print(f"Wrote {count} video sources to {args.output}")


if __name__ == "__main__":
    main()
