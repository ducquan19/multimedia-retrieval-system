from dataclasses import dataclass

from models.query import Daypart, Weather


@dataclass(frozen=True, slots=True)
class TrafficCamera:
    camera_id: str
    name: str
    streets: tuple[str, ...]
    video_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TrafficOptions:
    """The values the traffic filters can take, read from the traffic camera metadata."""

    available: bool
    cameras: tuple[TrafficCamera, ...]
    dates: tuple[str, ...]
    dayparts: tuple[Daypart, ...]
    weathers: tuple[Weather, ...]
