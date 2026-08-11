from pydantic import BaseModel, ConfigDict

from models.keyframe import Keyframe


class ScoredCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    result_id: str
    keyframe: Keyframe
    similarity_score: float
    image_path: str
