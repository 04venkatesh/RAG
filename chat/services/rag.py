import logging
import re
from typing import Dict, Any, Optional
from django.conf import settings
from django.contrib.auth.models import User
from . import retriever
from . import prompt_builder
from . import llm
from ..models import ChatSession

logger = logging.getLogger(__name__)

FALLBACK_NO_CONTEXT_MESSAGE = "I couldn't find enough relevant information in your uploaded documents to answer that question."

# Generic "whole document" questions (e.g. "explain about this pdf", "summarize this
# document", or even a single bare word like "explain") don't share vocabulary with
# the specific facts inside the document, so their embeddings often score BELOW the
# relevance threshold against every chunk even though the document is clearly what
# the user means. We detect this class of question and skip the strict similarity
# filter for it, instead just taking the top-scoring chunks so there's still
# something to summarize from.
GENERIC_DOCUMENT_QUERY_PATTERNS = [
    r"\bexplain\b.*\b(this|the|my)\b.*\b(pdf|document|doc|file)s?\b",
    r"\bsummar(y|ize|ise)\b",
    r"\boverview\b",
    r"\bwhat('?s| is)\b.*\b(this|the|my)\b.*\b(pdf|document|doc|file)s?\b.*\babout\b",
    r"\btell me about\b.*\b(this|the|my)\b.*\b(pdf|document|doc|file)s?\b",
    r"\bwhat does\b.*\b(this|the|my)\b.*\b(pdf|document|doc|file)s?\b.*\b(say|contain)\b",
    # Bare one/two-word requests with no real content to embed against, e.g. just
    # "explain", "explain this", "help", "go on" typed on their own.
    r"^(explain|summarize|summarise|elaborate|describe|help)(\s+(this|it|more))?[\s.!?]*$",
]

# When bypassing the relevance filter for a generic query, pull more chunks than the
# usual top_k so the LLM has enough of the document to actually summarize.
GENERIC_QUERY_TOP_K = 10

# Fallback threshold used when the configured SIMILARITY_THRESHOLD rejects every
# chunk for what is otherwise a normal, specific question. all-MiniLM-L6-v2 (and
# small sentence-embedding models generally) frequently score genuinely relevant
# short-query-vs-long-passage pairs in the 0.3-0.5 range, so a single hard cutoff
# (e.g. 0.45) can silently reject good matches. Rather than give up immediately,
# we retry once with a materially relaxed threshold before showing the "no
# information found" fallback -- this only fires when the strict pass found
# nothing at all, so it never overrides a threshold that's already permissive.
RELAXED_THRESHOLD_FLOOR = 0.20


def _is_generic_document_query(question: str) -> bool:
    q = question.lower().strip()
    return any(re.search(pattern, q) for pattern in GENERIC_DOCUMENT_QUERY_PATTERNS)


def answer_question(
    user: User,
    question: str,
    session: Optional[ChatSession] = None,
    top_k: Optional[int] = None,
    similarity_threshold: Optional[float] = None
) -> Dict[str, Any]:
    """
    Executes the complete local RAG pipeline:
    1. Query Embedding & Vector Similarity Search in ChromaDB (enforcing user_id)
    2. Cosine Similarity Calculation & Relevance Threshold Filter
    3. Relevance Check:
       - If no chunks qualify: returns controlled fallback without querying the LLM.
    4. Context Construction from verified chunks
    5. Injection-resistant Prompt Construction including conversation history
    6. Local LLM Generation via Ollama (Mistral)
    7. Source Citation Assembly
    """
    logger.info(f"=== [RAG PIPELINE START] User {user.id}: '{question}' ===")

    # 0. Detect generic "whole document" questions and relax the relevance filter
    # for them, since their embeddings often don't score well against specific
    # document content even when the document is exactly what's being asked about.
    is_generic = _is_generic_document_query(question)
    effective_top_k = top_k if top_k is not None else (GENERIC_QUERY_TOP_K if is_generic else None)
    effective_threshold = 0.0 if (is_generic and similarity_threshold is None) else similarity_threshold

    if is_generic:
        logger.info(
            "[RAG] Detected a generic whole-document question. "
            "Bypassing the similarity threshold and widening top_k."
        )

    # 1. Retrieve relevant chunks from ChromaDB
    retrieved_chunks = retriever.retrieve_relevant_chunks(
        user=user,
        query=question,
        top_k=effective_top_k,
        similarity_threshold=effective_threshold
    )

    # 1b. Relaxed retry: if the strict threshold rejected everything, don't give up
    # immediately. Small sentence-embedding models routinely score genuinely relevant
    # short-query-vs-long-passage pairs lower than a single fixed cutoff expects, so
    # retry once with a much more permissive threshold before showing the fallback.
    used_relaxed_threshold = False
    if not retrieved_chunks and not is_generic:
        configured_threshold = (
            similarity_threshold if similarity_threshold is not None
            else getattr(settings, 'SIMILARITY_THRESHOLD', 0.70)
        )
        if configured_threshold > RELAXED_THRESHOLD_FLOOR:
            logger.info(
                f"[RAG] No chunks passed threshold {configured_threshold:.2f}. "
                f"Retrying with relaxed threshold {RELAXED_THRESHOLD_FLOOR:.2f}."
            )
            retrieved_chunks = retriever.retrieve_relevant_chunks(
                user=user,
                query=question,
                top_k=top_k,
                similarity_threshold=RELAXED_THRESHOLD_FLOOR
            )
            used_relaxed_threshold = bool(retrieved_chunks)

    # 2. Relevance threshold check
    if not retrieved_chunks:
        logger.info("[RAG] No chunks passed the similarity threshold. Returning controlled fallback response.")
        return {
            "answer": FALLBACK_NO_CONTEXT_MESSAGE,
            "sources": [],
            "retrieved_count": 0,
        }

    if used_relaxed_threshold:
        logger.info(f"[RAG] Relaxed retry found {len(retrieved_chunks)} chunk(s).")

    # 3. Retrieve conversation history if session is provided
    history_limit = getattr(settings, 'CHAT_HISTORY_LIMIT', 10)
    conversation_history = []
    if session:
        past_msgs = session.messages.order_by('-created_at')[:history_limit]
        # Reverse to chronological order (oldest first)
        for m in reversed(past_msgs):
            conversation_history.append({
                "role": m.role,
                "content": m.content
            })

    # 4. Construct Prompt
    prompt = prompt_builder.build_rag_prompt(
        question=question,
        context_chunks=retrieved_chunks,
        conversation_history=conversation_history
    )

    logger.debug(f"[RAG PROMPT TO OLLAMA]:\n{prompt}")

    # 5. Call local Ollama
    answer = llm.generate(prompt)

    logger.debug(f"[RAG OLLAMA RESPONSE]:\n{answer}")

    # 6. Format verified sources (deduplicate while preserving highest score)
    seen_sources = set()
    verified_sources = []

    for c in retrieved_chunks:
        doc_id = c.get("document_id")
        doc_name = c.get("document_name")
        page = c.get("page_number")
        score = c.get("score")
        content = c.get("content", "")

        dedup_key = (doc_name, page)
        if dedup_key not in seen_sources:
            seen_sources.add(dedup_key)
            snippet = content.replace("\n", " ").strip()
            if len(snippet) > 160:
                snippet = snippet[:157] + "..."

            verified_sources.append({
                "document_id": doc_id,
                "document_name": doc_name,
                "page": page,
                "score": score,
                "snippet": snippet,
            })

    logger.info(f"=== [RAG PIPELINE COMPLETE] Generated response with {len(verified_sources)} source citations ===")

    return {
        "answer": answer,
        "sources": verified_sources,
        "retrieved_count": len(retrieved_chunks)
    }
