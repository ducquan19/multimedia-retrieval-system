"""Turns ranked candidates into the API result models (URLs, objects, traffic fields)."""

import uuid
from typing import Any

from models.candidate import ScoredCandidate
from models.keyframe import Keyframe
from repositories.object_repository import KeyframeObjectRepository
from repositories.traffic_repository import TrafficMetadataRepository
from schemas.search import SingleSearchResult, TRAKEEventResult, TRAKESearchResult
from services.retrieval.trake import TrakeSequence


def media_url(image_path: str) -> str:
    # Served by the /media mount; stable URLs let the browser cache keyframes across searches.
    return f"/media/{image_path}"


class ResultPresenter:
    def __init__(
        self,
        object_repository: KeyframeObjectRepository | None = None,
        traffic_repository: TrafficMetadataRepository | None = None,
    ) -> None:
        self._object_repository = object_repository
        self._traffic_repository = traffic_repository

    def objects_for(self, keyframe: Keyframe) -> list[dict[str, Any]]:
        """Objects stored in the manifest, else the ones of the object index."""
        if keyframe.objects:
            return keyframe.objects
        if self._object_repository is None:
            return []
        return self._object_repository.objects_for(keyframe.keyframe_id)

    def single(self, candidates: list[ScoredCandidate]) -> tuple[SingleSearchResult, ...]:
        return tuple(
            SingleSearchResult(
                result_id=candidate.keyframe.keyframe_id,
                rank=rank,
                video_id=candidate.keyframe.video_id,
                frame_id=candidate.keyframe.frame_id,
                keyframe_url=media_url(candidate.image_path),
                image_path=candidate.image_path,
                segment_id=candidate.keyframe.segment_id or "",
                asr_text=candidate.keyframe.asr_text or "",
                objects=self.objects_for(candidate.keyframe),
                similarity_score=candidate.similarity_score,
                answer="",
                time_ms=candidate.keyframe.time_ms,
                **self._traffic_fields(candidate.keyframe),
            )
            for rank, candidate in enumerate(candidates, start=1)
        )

    def trake(self, sequences: list[TrakeSequence]) -> tuple[TRAKESearchResult, ...]:
        return tuple(
            TRAKESearchResult(
                result_id=str(
                    uuid.uuid5(uuid.NAMESPACE_URL, "|".join(c.keyframe.keyframe_id for c in seq))
                ),
                rank=rank,
                video_id=seq[0].keyframe.video_id,
                similarity_score=total_score,
                events=tuple(
                    TRAKEEventResult(
                        event_index=position,
                        frame_id=c.keyframe.frame_id,
                        keyframe_url=media_url(c.image_path),
                        segment_id=c.keyframe.segment_id or "",
                        asr_text=c.keyframe.asr_text or "",
                        objects=self.objects_for(c.keyframe),
                        similarity_score=c.similarity_score,
                    )
                    for position, c in enumerate(seq, start=1)
                ),
            )
            for rank, (total_score, seq) in enumerate(sequences, start=1)
        )

    def _traffic_fields(self, keyframe: Keyframe) -> dict[str, str | None]:
        if self._traffic_repository is None:
            return {}
        video = self._traffic_repository.video(keyframe.video_id)
        if video is None:
            return {}
        clock = self._traffic_repository.clock_time(keyframe)
        return {
            "camera_name": video.camera_name,
            "clock_time": clock.strftime("%d/%m %H:%M:%S") if clock else None,
            "weather": video.weather or None,
        }
