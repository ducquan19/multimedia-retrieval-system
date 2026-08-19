from contextlib import asynccontextmanager
from fastapi import FastAPI

from core.config import get_settings
from core.logger import SimpleLogger
from repositories.keyframe_metadata_repository import KeyframeMetadataRepository
from infrastructure.embedding_service import EmbeddingService
from repositories.vector_repository import KeyframeVectorRepository
from repositories.text_repository import KeyframeTextRepository
from infrastructure.blip2_reranker import BLIP2Reranker
from services.retrieval_service import RetrievalService
from services.search_service import SearchService
from services.submission_service import SubmissionService

from infrastructure.submission_csv import CsvSubmissionFormatter

logger = SimpleLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan context manager for startup and shutdown events.
    Handles heavy initialization like loading FAISS indexes and AI models.
    """
    logger.info("Starting up application...")
    
    try:
        resolved_settings = get_settings()
        
        # 1. Keyframe Metadata
        logger.info("Initializing Keyframe Metadata Repository...")
        keyframe_repository = KeyframeMetadataRepository(
            resolved_settings.data_root,
            resolved_settings.keyframes_filename,
        )
        
        # 2. Embedding Service
        logger.info("Initializing Embedding Service (SigLIP & BEiT3)...")
        embedding_service = EmbeddingService()
        
        # 3. Vector Repositories (FAISS)
        logger.info(f"Loading FAISS SigLIP index from {resolved_settings.faiss_siglip_path}...")
        siglip_vector_repo = KeyframeVectorRepository(
            index_path=resolved_settings.faiss_siglip_path, 
            index_dim=1152,
            keyframe_repository=keyframe_repository
        )
        
        logger.info(f"Loading FAISS BEiT3 index from {resolved_settings.faiss_beit3_path}...")
        beit3_vector_repo = KeyframeVectorRepository(
            index_path=resolved_settings.faiss_beit3_path,
            index_dim=768,
            keyframe_repository=keyframe_repository
        )
        
        # 4. Text Repository (Elasticsearch)
        logger.info(f"Initializing Elasticsearch Repository at {resolved_settings.es_url}...")
        text_repository = KeyframeTextRepository(resolved_settings.es_url, keyframe_repository)
        
        # 5. Reranker
        logger.info(f"Initializing BLIP-2 Reranker (enabled={resolved_settings.enable_reranking})...")
        blip2_reranker = BLIP2Reranker(resolved_settings.data_root, resolved_settings.enable_reranking)
        
        # 6. Core Services
        logger.info("Initializing Retrieval Service...")
        retrieval_service = RetrievalService(
            siglip_vector_repo=siglip_vector_repo,
            beit3_vector_repo=beit3_vector_repo,
            text_repository=text_repository,
            blip2_reranker=blip2_reranker,
            embedding_service=embedding_service
        )
        
        # 7. Query Enhancer
        logger.info("Initializing Query Enhancer...")
        from infrastructure.query_enhancer import GeminiQueryEnhancer
        query_enhancer = GeminiQueryEnhancer(api_key=resolved_settings.gemini_api_key)
        
        # 8. Search Service
        logger.info("Initializing Search Service...")
        search_service = SearchService(
            retrieval_engine=retrieval_service,
            query_enhancer=query_enhancer,
            max_trake_events=resolved_settings.max_trake_events,
            max_query_length=resolved_settings.max_query_length,
            data_root=resolved_settings.data_root
        )
        
        logger.info("Initializing Submission Service...")
        submission_service = SubmissionService(
            CsvSubmissionFormatter(), resolved_settings.max_answer_length
        )
        
        # Attach to app.state
        app.state.search_service = search_service
        app.state.submission_service = submission_service
        
        logger.info("Application startup completed successfully.")
        
    except Exception as e:
        logger.error(f"Failed to start application: {e}")
        logger.exception(str(e))
        raise
        
    yield
    
    logger.info("Shutting down application...")
    try:
        # Cleanup can go here if needed
        logger.info("Application shutdown completed successfully.")
    except Exception as e:
        logger.error(f"Error during shutdown: {e}")
