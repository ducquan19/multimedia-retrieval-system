import csv
import json
import logging
import threading
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
_DAYPARTS = ("morning", "midday", "night")
_ALLOWED_CACHE_SIZE = 64


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


@dataclass(frozen=True)
class _KeyframeTable:
    """Per-keyframe arrays used to evaluate metadata filters with numpy."""

    traffic_mask: np.ndarray  # bool, one entry per keyframe
    non_traffic_mask: np.ndarray
    traffic_ids: np.ndarray  # FAISS ids of the traffic keyframes
    traffic_videos: np.ndarray  # video id of each traffic keyframe
    traffic_minutes: np.ndarray  # OSD minute of day of each traffic keyframe, -1 when unknown


class TrafficMetadataRepository:
    """Camera/time/weather metadata of the traffic videos (N) and metadata filtering.

    Sources (all under data_root):
      - traffic_camera/cameras.json: camera names, streets and per-video date/clock/daypart
      - traffic_camera/video_weather.csv: wet/dry label per video (optional)
      - video_sources.json: time_offset_ms (pts of the first frame) per video
    A keyframe's wall-clock time is the OSD clock of the first frame plus its offset in the video.
    Restrictions are returned as boolean masks over FAISS ids (positions in keyframes.json).
    """

    def __init__(self, data_root: Path, keyframe_repository: KeyframeMetadataRepository) -> None:
        self._data_root = data_root
        self._keyframe_repository = keyframe_repository
        self._lock = threading.Lock()
        self._cameras: tuple[TrafficCamera, ...] = ()
        self._videos: dict[str, TrafficVideo] = {}
        self._table: _KeyframeTable | None = None
        self._allowed_cache: dict[TrafficFilters, np.ndarray] = {}
        self._loaded = False

    @property
    def available(self) -> bool:
        self.load()
        return bool(self._videos)

    def load(self) -> None:
        if self._loaded:
            return
        with self._lock:
            if not self._loaded:
                self._read_metadata()
                self._loaded = True

    def _read_metadata(self) -> None:
        cameras_path = self._data_root / "traffic_camera" / "cameras.json"
        if not cameras_path.exists():
            logger.warning("Traffic camera metadata not found at %s", cameras_path)
            return

        weather: dict[str, str] = {}
        weather_path = self._data_root / "traffic_camera" / "video_weather.csv"
        if weather_path.exists():
            with open(weather_path, encoding="utf-8") as f:
                weather = {row["video_id"]: row["weather"] for row in csv.DictReader(f)}
        offsets: dict[str, int] = {}
        sources_path = self._data_root / "video_sources.json"
        if sources_path.exists():
            videos = json.loads(sources_path.read_text(encoding="utf-8")).get("videos", {})
            offsets = {vid: int(entry.get("time_offset_ms", 0)) for vid, entry in videos.items()}

        cameras = []
        traffic_videos: dict[str, TrafficVideo] = {}
        for camera in json.loads(cameras_path.read_text(encoding="utf-8"))["cameras"]:
            video_ids = []
            for video in camera["videos"]:
                video_id = video["video_id"]
                video_ids.append(video_id)
                traffic_videos[video_id] = TrafficVideo(
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
        self._videos = traffic_videos
        logger.info(
            "Loaded traffic metadata: %d cameras, %d videos", len(cameras), len(traffic_videos)
        )

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
            dayparts=tuple(p for p in _DAYPARTS if any(v.daypart == p for v in videos)),
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

    def warm_up(self) -> None:
        """Build the per-keyframe filter arrays now instead of on the first TRAFFIC query."""
        self._keyframe_table()

    def non_traffic_mask(self) -> np.ndarray:
        """Mask of every keyframe outside the traffic videos (KIS, TRAKE, VQA)."""
        return self._keyframe_table().non_traffic_mask

    def allowed_mask(self, filters: TrafficFilters) -> np.ndarray:
        """Mask of the traffic keyframes that pass every metadata filter (cached)."""
        cached = self._allowed_cache.get(filters)
        if cached is not None:
            return cached
        table = self._keyframe_table()
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
        keep = np.isin(table.traffic_videos, videos)
        if filters.clock_from:
            keep &= table.traffic_minutes >= self._minute_of_day(filters.clock_from)
        if filters.clock_to:
            keep &= (table.traffic_minutes >= 0) & (
                table.traffic_minutes <= self._minute_of_day(filters.clock_to)
            )
        mask = np.zeros_like(table.traffic_mask)
        mask[table.traffic_ids[keep]] = True
        with self._lock:
            if len(self._allowed_cache) >= _ALLOWED_CACHE_SIZE:
                self._allowed_cache.pop(next(iter(self._allowed_cache)))
            self._allowed_cache[filters] = mask
        return mask

    def _keyframe_table(self) -> _KeyframeTable:
        table = self._table
        if table is not None:
            return table
        self.load()
        keyframes = self._keyframe_repository.load().keyframes
        with self._lock:
            if self._table is None:
                traffic_mask = np.fromiter(
                    (is_traffic_video(k.video_id) for k in keyframes),
                    dtype=bool,
                    count=len(keyframes),
                )
                traffic_ids = np.flatnonzero(traffic_mask).astype(np.int64)
                minutes = []
                for i in traffic_ids.tolist():
                    clock = self.clock_time(keyframes[i])
                    minutes.append(clock.hour * 60 + clock.minute if clock else -1)
                self._table = _KeyframeTable(
                    traffic_mask=traffic_mask,
                    non_traffic_mask=~traffic_mask,
                    traffic_ids=traffic_ids,
                    traffic_videos=np.array([keyframes[i].video_id for i in traffic_ids.tolist()]),
                    traffic_minutes=np.asarray(minutes, dtype=np.int32),
                )
            return self._table

    @staticmethod
    def _minute_of_day(clock: str) -> int:
        hours, minutes = clock.split(":")
        return int(hours) * 60 + int(minutes)
