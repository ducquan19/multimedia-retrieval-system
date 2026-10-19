"""Modality weights of the hybrid search, shared by retrieval and the response metadata.

Keeping one implementation guarantees that the weights reported in ``applied_weights`` are
the weights the retrieval engine actually fused with.
"""

from dataclasses import dataclass

from core.constants import MANUAL_OBJECT_WEIGHT
from models.query import ObjectQueryTerm, QueryVariants, SearchSources


@dataclass(frozen=True)
class ModalityWeights:
    vis: float
    asr: float
    obj: float

    def as_dict(self) -> dict[str, float]:
        return {"w_vis": self.vis, "w_asr": self.asr, "w_obj": self.obj}


def merge_object_terms(
    manual: tuple[ObjectQueryTerm, ...], automatic: tuple[ObjectQueryTerm, ...]
) -> tuple[ObjectQueryTerm, ...]:
    """Manual object terms first; automatic ones only add labels that are not already there."""
    labels = {term.label.casefold() for term in manual}
    return manual + tuple(term for term in automatic if term.label.casefold() not in labels)


def object_terms_for(
    sources: SearchSources,
    manual: tuple[ObjectQueryTerm, ...],
    enhanced: QueryVariants | None,
    object_search_available: bool,
) -> tuple[ObjectQueryTerm, ...]:
    if not sources.object or not object_search_available:
        return ()
    return merge_object_terms(manual, enhanced.objects if enhanced else ())


def resolve_weights(
    sources: SearchSources,
    enhanced: QueryVariants | None,
    manual_objects: tuple[ObjectQueryTerm, ...],
    object_terms: tuple[ObjectQueryTerm, ...],
) -> ModalityWeights:
    """Sources are the modalities the user allows; Gemini weights modulate them."""
    has_objects = bool(object_terms)
    defaults = ModalityWeights(
        vis=1.0 if sources.image else 0.0,
        asr=1.0 if sources.asr else 0.0,
        obj=1.0 if has_objects else 0.0,
    )
    if enhanced is None:
        return defaults

    w_obj = enhanced.w_obj if enhanced.objects else 0.0
    if manual_objects:
        w_obj = max(w_obj, MANUAL_OBJECT_WEIGHT)
    weights = ModalityWeights(
        vis=enhanced.w_vis if sources.image else 0.0,
        asr=enhanced.w_asr if sources.asr else 0.0,
        obj=w_obj if has_objects else 0.0,
    )
    if weights.vis + weights.asr + weights.obj == 0:
        # Gemini weighted only disabled modalities: fall back to the enabled ones.
        return defaults
    return weights
