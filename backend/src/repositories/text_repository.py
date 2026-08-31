import logging
import uuid

from elasticsearch import Elasticsearch

from core.intro_exclusion import IntroExclusionPolicy
from repositories.keyframe_metadata_repository import KeyframeMetadataRepository
from schemas.retrieval import ScoredCandidate

logger = logging.getLogger(__name__)


class KeyframeTextRepository:
    _MAX_TERMS_PER_CLAUSE = 65_536

    def __init__(
        self,
        es_url: str,
        keyframe_repository: KeyframeMetadataRepository,
        intro_exclusion_policy: IntroExclusionPolicy | None = None,
    ):
        self.es = Elasticsearch(es_url)
        self.index_name = "keyframes_metadata"
        self._keyframe_repository = keyframe_repository
        self._intro_exclusion_policy = intro_exclusion_policy or IntroExclusionPolicy()

    def ping(self) -> bool:
        try:
            return self.es.ping()
        except Exception as e:
            logger.error("Failed to ping Elasticsearch: %s", e)
            return False

    def search_text(
        self,
        text_query: str,
        fields: list[str],
        objects: list[str] | None,
        top_k: int,
    ) -> list[ScoredCandidate]:
        """
        Searches Elasticsearch using BM25 on specified text fields and filters by objects.
        Returns a list of ScoredCandidate.
        """
        if not self.ping():
            return []

        must_clauses = []
        if text_query and fields:
            must_clauses.append({
                "multi_match": {
                    "query": text_query,
                    "fields": fields,
                    "type": "best_fields"
                }
            })

        filter_clauses = []
        if objects:
            for obj in objects:
                filter_clauses.append({
                    "match": {
                        "objects": obj
                    }
                })

        collection = self._keyframe_repository.load()
        excluded_ids = self._intro_exclusion_policy.excluded_faiss_ids(collection)
        must_not_clauses = [
            {
                "terms": {
                    "faiss_id": list(
                        excluded_ids[offset : offset + self._MAX_TERMS_PER_CLAUSE]
                    )
                }
            }
            for offset in range(0, len(excluded_ids), self._MAX_TERMS_PER_CLAUSE)
        ]

        query_body = {
            "size": top_k,
            "query": {
                "bool": {
                    "must": must_clauses if must_clauses else {"match_all": {}},
                    "filter": filter_clauses,
                    "must_not": must_not_clauses,
                }
            },
            "_source": ["faiss_id"]
        }

        try:
            response = self.es.search(index=self.index_name, body=query_body)
            hits = response["hits"]["hits"]

            # Map hits to ScoredCandidate
            candidates = []

            for hit in hits:
                faiss_id = hit["_source"]["faiss_id"]
                score = hit["_score"] or 0.0
                try:
                    keyframe = collection.keyframes[faiss_id]
                    if self._intro_exclusion_policy.is_intro(keyframe):
                        continue
                    candidate = ScoredCandidate(
                        result_id=str(uuid.uuid4()),
                        keyframe=keyframe,
                        similarity_score=score,
                        image_path=keyframe.image_path,
                    )
                    candidates.append(candidate)
                except IndexError:
                    logger.warning("ES returned faiss_id %d which is out of bounds", faiss_id)

            return candidates
        except Exception as e:
            logger.error("Elasticsearch search failed: %s", e)
            return []
