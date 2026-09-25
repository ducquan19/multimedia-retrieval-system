import csv
import json
import logging
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from models.keyframe import Keyframe
from repositories.keyframe_metadata_repository import KeyframeMetadataRepository
from schemas.search import TrafficCamera, TrafficFilters, TrafficOptionsResponse

logger = logging.getLogger(__name__)

TRAFFIC_PREFIX = "N"


def is_traffic_video(video_id: str) -> bool:
    return video_id.startswith(TRAFFIC_PREFIX)


def fold(text: str) -> str:
    """Case- and accent-insensitive key: "Lê Hồng Phong" -> "le hong phong"."""
    decomposed = unicodedata.normalize("NFD", text.replace("đ", "d").replace("Đ", "D"))
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn").casefold()


@dataclass(frozen=True)
class TrafficVideo:
    video_id: str
    camera_id: str
    camera_name: str
    date: str
    daypart: str
    weather: str
    clock_start: datetime | None
    time_offset_ms: int


class TrafficMetadataRepository:
    """Camera/time/weather metadata of the traffic videos (N) and metadata filtering.

    Sources (all under data_root):
      - traffic_camera/cameras.json: camera names, streets and per-video date/clock/daypart
      - traffic_camera/video_weather.csv: wet/dry label per video (optional)
      - video_sources.json: time_offset_ms (pts of the first frame) per video
    A keyframe's wall-clock time is the OSD clock of the first frame plus its offset in the video.
    """

    def __init__(self, data_root: Path, keyframe_repository: KeyframeMetadataRepository) -> None:
        self._data_root = data_root
        self._keyframe_repository = keyframe_repository
        self._cameras: tuple[TrafficCamera, ...] = ()
        self._videos: dict[str, TrafficVideo] = {}
        self._traffic_ids: np.ndarray | None = None
        self._non_traffic_ids: np.ndarray | None = None
        self._traffic_videos: np.ndarray | None = None
        self._traffic_minutes: np.ndarray | None = None
        self._allowed_cache: dict[TrafficFilters, np.ndarray] = {}
        self._loaded = False

    @property
    def available(self) -> bool:
        self.load()
        return bool(self._videos)

    def load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        cameras_path = self._data_root / "traffic_camera" / "cameras.json"
        if not cameras_path.exists():
            logger.warning("Traffic camera metadata not found at %s", cameras_path)
            return

        weather = {}
        weather_path = self._data_root / "traffic_camera" / "video_weather.csv"
        if weather_path.exists():
            with open(weather_path, encoding="utf-8") as f:
                weather = {row["video_id"]: row["weather"] for row in csv.DictReader(f)}
        offsets = {}
        sources_path = self._data_root / "video_sources.json"
        if sources_path.exists():
            videos = json.loads(sources_path.read_text(encoding="utf-8")).get("videos", {})
            offsets = {vid: int(entry.get("time_offset_ms", 0)) for vid, entry in videos.items()}

        cameras = []
        for camera in json.loads(cameras_path.read_text(encoding="utf-8"))["cameras"]:
            video_ids = []
            for video in camera["videos"]:
                video_id = video["video_id"]
                video_ids.append(video_id)
                self._videos[video_id] = TrafficVideo(
                    video_id=video_id,
                    camera_id=camera["camera_id"],
                    camera_name=camera["display_name"],
                    date=video.get("date") or "",
                    daypart=video.get("daypart") or "",
                    weather=weather.get(video_id, ""),
                    clock_start=self._parse_clock(video.get("date"), video.get("clock_start")),
                    time_offset_ms=offsets.get(video_id, 0),
                )
            cameras.append(
                TrafficCamera(
                    camera_id=camera["camera_id"],
                    name=camera["display_name"],
                    streets=tuple(camera.get("streets", ())),
                    video_ids=tuple(video_ids),
                )
            )
        self._cameras = tuple(sorted(cameras, key=lambda c: fold(c.name)))
        logger.info("Loaded traffic metadata: %d cameras, %d videos", len(cameras), len(self._videos))

    @staticmethod
    def _parse_clock(date: str | None, clock: str | None) -> datetime | None:
        if not date or not clock:
            return None
        try:
            return datetime.strptime(f"{date} {clock}", "%Y-%m-%d %H:%M:%S.%f")
        except ValueError:
            return None

    def options(self) -> TrafficOptionsResponse:
        self.load()
        videos = self._videos.values()
        return TrafficOptionsResponse(
            available=bool(self._videos),
            cameras=self._cameras,
            dates=tuple(sorted({v.date for v in videos if v.date})),
            dayparts=tuple(p for p in ("morning", "midday", "night") if any(v.daypart == p for v in videos)),
            weathers=tuple(sorted({v.weather for v in videos if v.weather})),
        )

    def video(self, video_id: str) -> TrafficVideo | None:
        self.load()
        return self._videos.get(video_id)

    def clock_time(self, keyframe: Keyframe) -> datetime | None:
        """OSD wall-clock time shown on this keyframe."""
        video = self.video(keyframe.video_id)
        if video is None or video.clock_start is None or keyframe.time_ms is None:
            return None
        return video.clock_start + timedelta(milliseconds=keyframe.time_ms - video.time_offset_ms)

    def traffic_ids(self) -> np.ndarray:
        """FAISS ids of every traffic keyframe."""
        self._split_ids()
        assert self._traffic_ids is not None
        return self._traffic_ids

    def non_traffic_ids(self) -> np.ndarray:
        """FAISS ids of every keyframe outside the traffic videos (e.g. for TRAKE)."""
        self._split_ids()
        assert self._non_traffic_ids is not None
        return self._non_traffic_ids

    def _split_ids(self) -> None:
        if self._traffic_ids is not None:
            return
        self.load()
        keyframes = self._keyframe_repository.load().keyframes
        mask = np.array([is_traffic_video(k.video_id) for k in keyframes], dtype=bool)
        self._traffic_ids = np.flatnonzero(mask).astype(np.int64)
        self._non_traffic_ids = np.flatnonzero(~mask).astype(np.int64)
        # Per traffic keyframe: its video and OSD minute of day (-1 when unknown).
        self._traffic_videos = np.array([keyframes[i].video_id for i in self._traffic_ids.tolist()])
        minutes = []
        for i in self._traffic_ids.tolist():
            clock = self.clock_time(keyframes[i])
            minutes.append(clock.hour * 60 + clock.minute if clock else -1)
        self._traffic_minutes = np.asarray(minutes, dtype=np.int32)

    def allowed_ids(self, filters: TrafficFilters) -> np.ndarray:
        """FAISS ids of traffic keyframes that pass every metadata filter (cached)."""
        cached = self._allowed_cache.get(filters)
        if cached is not None:
            return cached
        self._split_ids()
        cameras = set(filters.camera_ids)
        dates = set(filters.dates)
        dayparts = set(filters.dayparts)
        weathers = set(filters.weathers)
        videos = [
            video_id
            for video_id, video in self._videos.items()
            if (not cameras or video.camera_id in cameras)
            and (not dates or video.date in dates)
            and (not dayparts or video.daypart in dayparts)
            and (not weathers or video.weather in weathers)
        ]
        mask = np.isin(self._traffic_videos, videos)
        if filters.clock_from:
            mask &= self._traffic_minutes >= self._minute_of_day(filters.clock_from)
        if filters.clock_to:
            mask &= (self._traffic_minutes >= 0) & (
                self._traffic_minutes <= self._minute_of_day(filters.clock_to)
            )
        allowed = self._traffic_ids[mask]
        if len(self._allowed_cache) >= 64:
            self._allowed_cache.pop(next(iter(self._allowed_cache)))
        self._allowed_cache[filters] = allowed
        return allowed

    @staticmethod
    def _minute_of_day(clock: str) -> int:
        hours, minutes = clock.split(":")
        return int(hours) * 60 + int(minutes)
