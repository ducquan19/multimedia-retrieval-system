import logging
from typing import Optional

from elasticsearch import Elasticsearch

logger = logging.getLogger(__name__)


import uuid
from repositories.keyframe_metadata_repository import KeyframeMetadataRepository
from schemas.retrieval import ScoredCandidate


class KeyframeTextRepository:
    def __init__(self, es_url: str, keyframe_repository: KeyframeMetadataRepository):
        self.es = Elasticsearch(es_url)
        self.index_name = "keyframes_metadata"
        self._keyframe_repository = keyframe_repository

    def ping(self) -> bool:
        try:
            return self.es.ping()
        except Exception as e:
            logger.error("Failed to ping Elasticsearch: %s", e)
            return False

    def search_text(self, text_query: str, fields: list[str], objects: Optional[list[str]], top_k: int) -> list[ScoredCandidate]:
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

        query_body = {
            "size": top_k,
            "query": {
                "bool": {
                    "must": must_clauses if must_clauses else {"match_all": {}},
                    "filter": filter_clauses
                }
            },
            "_source": ["faiss_id"]
        }

        try:
            response = self.es.search(index=self.index_name, body=query_body)
            hits = response["hits"]["hits"]

            # Map hits to ScoredCandidate
            collection = self._keyframe_repository.load()
            candidates = []

            for hit in hits:
                faiss_id = hit["_source"]["faiss_id"]
                score = hit["_score"] or 0.0
                try:
                    keyframe = collection.keyframes[faiss_id]
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
