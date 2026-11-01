import logging
from typing import List, Dict, Any, Optional
from django.conf import settings

logger = logging.getLogger(__name__)

# Global singleton client and collection holders
_CHROMA_CLIENT = None
_CHROMA_COLLECTION = None


def get_chroma_client():
    """
    Initializes and returns a persistent ChromaDB client pointing to CHROMA_PERSIST_DIRECTORY.
    Persistence ensures vectors survive application restarts.
    """
    global _CHROMA_CLIENT
    if _CHROMA_CLIENT is None:
        import chromadb
        persist_dir = str(settings.CHROMA_PERSIST_DIRECTORY)
        logger.info(f"Initializing ChromaDB PersistentClient at: {persist_dir}")
        _CHROMA_CLIENT = chromadb.PersistentClient(path=persist_dir)
    return _CHROMA_CLIENT


def get_collection():
    """
    Retrieves or creates the configured ChromaDB collection for document chunks.
    Configured with cosine space ('hnsw:space': 'cosine').
    
    EXPLANATION OF CHROMADB SIMILARITY METRIC:
    ChromaDB calculates cosine distance d in [0, 2]:
        d = 1 - (u · v) / (||u|| * ||v||)
    Where:
        d = 0.0 means vectors are identical (similarity = 1.0)
        d = 1.0 means vectors are orthogonal (similarity = 0.0)
        d = 2.0 means vectors are opposite (similarity = -1.0)
    Cosine similarity is therefore computed as: similarity = 1.0 - distance.
    """
    global _CHROMA_COLLECTION
    if _CHROMA_COLLECTION is None:
        client = get_chroma_client()
        coll_name = getattr(settings, 'CHROMA_COLLECTION_NAME', 'document_chunks')
        logger.info(f"Accessing ChromaDB collection: '{coll_name}' with cosine distance...")
        _CHROMA_COLLECTION = client.get_or_create_collection(
            name=coll_name,
            metadata={"hnsw:space": "cosine"}
        )
    return _CHROMA_COLLECTION


def add_chunks(
    ids: List[str],
    documents: List[str],
    embeddings: List[List[float]],
    metadatas: List[Dict[str, Any]],
    batch_size: int = 100
) -> None:
    """
    Adds document chunks to ChromaDB in batches.
    Guarantees that each vector has its content, embedding, and security metadata attached.
    """
    if not ids:
        return

    collection = get_collection()
    total = len(ids)

    for i in range(0, total, batch_size):
        batch_ids = ids[i:i + batch_size]
        batch_docs = documents[i:i + batch_size]
        batch_embs = embeddings[i:i + batch_size]
        batch_meta = metadatas[i:i + batch_size]

        # ChromaDB metadata values must be str, int, float, or bool
        sanitized_metas = []
        for m in batch_meta:
            clean_m = {}
            for k, v in m.items():
                if isinstance(v, (str, int, float, bool)):
                    clean_m[k] = v
                elif v is None:
                    continue
                else:
                    clean_m[k] = str(v)
            sanitized_metas.append(clean_m)

        collection.add(
            ids=batch_ids,
            documents=batch_docs,
            embeddings=batch_embs,
            metadatas=sanitized_metas
        )

    logger.info(f"Successfully added {total} chunks to ChromaDB.")


def query_chunks(
    query_embedding: List[float],
    user_id: int,
    n_results: int = 5,
    document_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Queries ChromaDB for chunks similar to the query embedding.
    
    MANDATORY SECURITY ENFORCEMENT:
    The search is STRICTLY restricted at the ChromaDB vector level using a metadata filter:
        where={"user_id": str(user_id)}
    This prevents cross-user information leakage. We NEVER search all vectors and filter in Python.
    """
    collection = get_collection()

    if document_id is not None:
        where_filter = {
            "$and": [
                {"user_id": str(user_id)},
                {"document_id": str(document_id)}
            ]
        }
    else:
        where_filter = {"user_id": str(user_id)}

    try:
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            where=where_filter,
            include=["documents", "metadatas", "distances"]
        )
        return results
    except Exception as e:
        logger.error(f"ChromaDB query failed for user {user_id}: {e}")
        raise


def delete_document_chunks(document_id: int, user_id: int) -> int:
    """
    Deletes all vectors belonging to a specific document and user from ChromaDB.
    Avoids leaving orphaned vectors in the vector store.
    """
    collection = get_collection()
    where_filter = {
        "$and": [
            {"document_id": str(document_id)},
            {"user_id": str(user_id)}
        ]
    }

    try:
        # First retrieve matching IDs
        existing = collection.get(where=where_filter)
        ids_to_delete = existing.get("ids", [])
        if ids_to_delete:
            collection.delete(ids=ids_to_delete)
            logger.info(f"Deleted {len(ids_to_delete)} vectors for document {document_id} from ChromaDB.")
            return len(ids_to_delete)
        return 0
    except Exception as e:
        logger.error(f"Failed to delete ChromaDB vectors for document {document_id}: {e}")
        raise


def delete_chunks_by_ids(ids: List[str]) -> None:
    """
    Deletes vectors explicitly by their unique Chroma IDs.
    Used for atomic rollbacks if database insertions fail.
    """
    if not ids:
        return
    collection = get_collection()
    try:
        collection.delete(ids=ids)
        logger.info(f"Deleted {len(ids)} vectors from ChromaDB by IDs.")
    except Exception as e:
        logger.error(f"Failed to delete ChromaDB vectors by IDs: {e}")
        raise



def get_structured_chunks(
    user_id: int,
    document_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Retrieves structured CSV/XLS/XLSX chunks directly from ChromaDB.

    This does not perform vector similarity search.

    It is used for whole-document operations such as:
        "Summarize my spreadsheet"

    Security:
        Results are restricted to the authenticated user's user_id.
    """

    collection = get_collection()

    if document_id is not None:
        where_filter = {
            "$and": [
                {
                    "user_id": str(user_id)
                },
                {
                    "document_id": str(document_id)
                }
            ]
        }
    else:
        where_filter = {
            "$and": [
                {
                    "user_id": str(user_id)
                },
                {
                    "file_type": {
                        "$in": [
                            "csv",
                            "xlsx",
                            "xls"
                        ]
                    }
                }
            ]
        }

    try:
        results = collection.get(
            where=where_filter,
            include=[
                "documents",
                "metadatas"
            ]
        )

        logger.info(
            f"Retrieved "
            f"{len(results.get('ids', []))} "
            f"structured chunks for user {user_id}"
        )

        return results

    except Exception as e:
        logger.error(
            f"Failed to retrieve structured chunks "
            f"for user {user_id}: {e}"
        )
        raise