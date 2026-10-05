from schemas.search import ObjectQueryTerm, QueryVariants, SearchSources
from services.weights import ModalityWeights, object_terms_for, resolve_weights

DOG = ObjectQueryTerm(label="Dog")
CAT = ObjectQueryTerm(label="cat")


def test_default_weights_follow_the_enabled_sources() -> None:
    sources = SearchSources(image=True, asr=True, object=True)

    assert resolve_weights(sources, None, (DOG,), (DOG,)) == ModalityWeights(1.0, 1.0, 1.0)
    # Object source enabled but nothing to search for (or no object index): no object weight.
    assert resolve_weights(sources, None, (), ()) == ModalityWeights(1.0, 1.0, 0.0)


def test_gemini_weights_are_gated_by_sources_and_manual_objects() -> None:
    enhanced = QueryVariants(variants=["a dog"], w_vis=0.8, w_asr=0.6, w_obj=0.2, objects=(DOG,))
    sources = SearchSources(image=True, asr=False, object=True)

    weights = resolve_weights(sources, enhanced, (CAT,), (CAT, DOG))

    # Manual objects keep at least MANUAL_OBJECT_WEIGHT (0.5).
    assert weights == ModalityWeights(0.8, 0.0, 0.5)


def test_weights_fall_back_when_gemini_only_weighted_disabled_sources() -> None:
    enhanced = QueryVariants(variants=["speech"], w_vis=0.0, w_asr=1.0)

    weights = resolve_weights(SearchSources(image=True, asr=False), enhanced, (), ())

    assert weights == ModalityWeights(1.0, 0.0, 0.0)


def test_object_terms_merge_manual_first_and_require_an_object_index() -> None:
    enhanced = QueryVariants(variants=["x"], objects=(ObjectQueryTerm(label="CAT"), DOG))
    sources = SearchSources(image=True, object=True)

    assert object_terms_for(sources, (CAT,), enhanced, True) == (CAT, DOG)
    assert object_terms_for(sources, (CAT,), enhanced, False) == ()
    assert object_terms_for(SearchSources(image=True), (CAT,), enhanced, True) == ()
