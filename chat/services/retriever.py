import logging
from typing import List, Dict, Any, Optional
from django.conf import settings
from django.contrib.auth.models import User
from documents.services import embedder, chroma

logger = logging.getLogger(__name__)

def retrieve_relevant_chunks(
    user: User,
    query: str,
    top_k: Optional[int] = None,
    similarity_threshold: Optional[float] = None,
    document_id: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Performs semantic vector retrieval against ChromaDB for an authenticated user.
    
    CRITICAL SECURITY RULE:
    The retrieval query MUST enforce the authenticated user_id inside the ChromaDB query filter.
    We NEVER retrieve all vectors and filter in Python.
    
    COSINE SIMILARITY CALCULATION:
    ChromaDB cosine space returns distance d = 1 - cos_sim.
    We convert distance to cosine similarity:
        similarity = 1.0 - distance
    A threshold (e.g. 0.70) filters out weakly related or noisy chunks.
    """
    top_k = top_k or getattr(settings, 'TOP_K', 5)
    similarity_threshold = similarity_threshold if similarity_threshold is not None else getattr(settings, 'SIMILARITY_THRESHOLD', 0.70)

    clean_query = query.strip()
    if not clean_query:
        return []

    logger.info("Retrieval initiated for user_id=%s; query_length=%s", user.id, len(clean_query))

    # 1. Embed query using the EXACT SAME model used during document ingestion
    query_embedding = embedder.embed_text(clean_query)
    emb_dim = len(query_embedding)
    logger.debug(f"Query embedded into {emb_dim}-dimensional vector.")

    # 2. Query ChromaDB with strict user_id security filter
    raw_results = chroma.query_chunks(
        query_embedding=query_embedding,
        user_id=user.id,
        n_results=top_k,
        document_id=document_id
    )

    ids = raw_results.get("ids", [[]])[0]
    docs = raw_results.get("documents", [[]])[0]
    metas = raw_results.get("metadatas", [[]])[0]
    distances = raw_results.get("distances", [[]])[0]

    retrieved_items = []

    for c_id, text, meta, dist in zip(ids, docs, metas, distances):
        # Convert cosine distance to cosine similarity
        # With normalized vectors in cosine space: distance is in [0, 2], similarity is 1.0 - distance
        raw_sim = 1.0 - dist
        similarity = max(0.0, min(1.0, raw_sim))

        logger.debug(
            f"Candidate chunk {c_id} from doc '{meta.get('document_name')}' | "
            f"Distance: {dist:.4f} | Similarity: {similarity:.4f} | Threshold: {similarity_threshold:.4f}"
        )

        # Apply relevance threshold filter
        if similarity >= similarity_threshold:
            doc_id_val = meta.get("document_id")
            try:
                doc_id_int = int(doc_id_val) if doc_id_val is not None else None
            except (ValueError, TypeError):
                doc_id_int = None

            page_num_val = meta.get("page_number")
            try:
                page_num_int = int(page_num_val) if page_num_val is not None else None
            except (ValueError, TypeError):
                page_num_int = None

            retrieved_items.append({
                "chunk_id": c_id,
                "document_id": doc_id_int,
                "document_name": meta.get("document_name", "Unknown Document"),
                "content": text,
                "page_number": page_num_int,
                "score": round(similarity, 4),
                "distance": round(dist, 4),
                "metadata": meta,
            })
        else:
            logger.info(
                f"Discarded chunk {c_id} below similarity threshold ({similarity:.4f} < {similarity_threshold:.4f})."
            )

    # Sort primarily by similarity score descending
    retrieved_items.sort(key=lambda x: x["score"], reverse=True)
    logger.info(f"Retrieval complete: {len(retrieved_items)} relevant chunk(s) met the similarity threshold.")

    return retrieved_items





def retrieve_structured_chunks(
    user: User,
    document_id: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Retrieves spreadsheet chunks directly from ChromaDB.

    This does NOT perform embedding or cosine similarity search.

    It is used for whole-document operations such as:

        "summarize"

        "summarize my spreadsheet"

        "give me an overview of the Excel file"
    """

    logger.info(
        f"Structured retrieval initiated for "
        f"User {user.id} ({user.username})"
        + (
            f", Document {document_id}"
            if document_id is not None
            else ""
        )
    )

    raw_results = chroma.get_structured_chunks(
        user_id=user.id,
        document_id=document_id
    )

    ids = raw_results.get(
        "ids",
        []
    )

    docs = raw_results.get(
        "documents",
        []
    )

    metas = raw_results.get(
        "metadatas",
        []
    )

    retrieved_items = []

    for c_id, text, meta in zip(
        ids,
        docs,
        metas
    ):

        doc_id_val = meta.get(
            "document_id"
        )

        try:
            doc_id_int = (
                int(doc_id_val)
                if doc_id_val is not None
                else None
            )
        except (
            ValueError,
            TypeError
        ):
            doc_id_int = None

        page_num_val = meta.get(
            "page_number"
        )

        try:
            page_num_int = (
                int(page_num_val)
                if page_num_val is not None
                else None
            )
        except (
            ValueError,
            TypeError
        ):
            page_num_int = None

        retrieved_items.append({
            "chunk_id": c_id,
            "document_id": doc_id_int,
            "document_name": meta.get(
                "document_name",
                "Unknown Document"
            ),
            "content": text,
            "page_number": page_num_int,
            "score": None,
            "distance": None,
            "metadata": meta,
        })

    retrieved_items.sort(
        key=lambda x: (
            x.get("document_id") or 0,
            x.get("metadata", {}).get(
                "chunk_index",
                0
            )
        )
    )

    logger.info(
        f"Structured retrieval complete: "
        f"{len(retrieved_items)} "
        f"chunk(s) retrieved."
    )

    return retrieved_items