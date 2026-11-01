import logging
from typing import List
from django.conf import settings

logger = logging.getLogger(__name__)

# Global singleton holder for SentenceTransformer model instance
_EMBEDDING_MODEL_INSTANCE = None


def get_embedding_model():
    """
    Retrieves the cached SentenceTransformer model instance or initializes it once.
    Avoids reloading weights on every chunk or query request.
    """
    global _EMBEDDING_MODEL_INSTANCE
    if _EMBEDDING_MODEL_INSTANCE is None:
        model_name = getattr(settings, 'EMBEDDING_MODEL', 'all-MiniLM-L6-v2')
        logger.info(f"Loading local SentenceTransformer model: '{model_name}'...")
        from sentence_transformers import SentenceTransformer
        _EMBEDDING_MODEL_INSTANCE = SentenceTransformer(model_name)
        logger.info(f"Loaded SentenceTransformer model '{model_name}'.")
    return _EMBEDDING_MODEL_INSTANCE


def get_embedding_dimension() -> int:
    """
    Returns the vector dimension of the active embedding model dynamically.
    For all-MiniLM-L6-v2, this returns 384.
    """
    model = get_embedding_model()
    return model.get_sentence_embedding_dimension()


def embed_text(text: str) -> List[float]:
    """
    Generates a dense vector embedding for a single string (such as a user query).
    
    CRITICAL RAG PRINCIPLE:
    The exact same embedding model MUST be used for both document chunks and user queries.
    Sentence embeddings map text into a specific learned geometric manifold.
    If queries and chunks were embedded using different models or dimensions,
    their coordinate systems would not match, completely breaking cosine similarity search.
    """
    model = get_embedding_model()
    embedding = model.encode(
        text,
        convert_to_numpy=True,
        normalize_embeddings=True
    )
    return embedding.tolist()


def embed_documents(texts: List[str], batch_size: int = 32) -> List[List[float]]:
    """
    Generates dense vector embeddings for a list of document chunks using batching.
    Batched inference dramatically improves throughput compared to single-item encoding.
    """
    if not texts:
        return []

    model = get_embedding_model()
    embeddings = model.encode(
        texts,
        batch_size=batch_size,
        show_progress_bar=False,
        convert_to_numpy=True,
        normalize_embeddings=True
    )
    return embeddings.tolist()
