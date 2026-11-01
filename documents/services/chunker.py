import re
import logging
from typing import List, Dict, Any
from django.conf import settings

logger = logging.getLogger(__name__)

class DocumentChunkDTO:
    """Data Transfer Object representing a processed chunk ready for embedding and storage."""
    def __init__(self, content: str, chunk_index: int, page_number: int = None, metadata: dict = None):
        self.content = content
        self.chunk_index = chunk_index
        self.page_number = page_number
        self.metadata = metadata or {}

    def to_dict(self):
        return {
            "content": self.content,
            "chunk_index": self.chunk_index,
            "page_number": self.page_number,
            "metadata": self.metadata,
        }


def _split_text_into_chunks(text: str, chunk_size: int, chunk_overlap: int) -> List[str]:
    """
    Recursively splits text respecting paragraph and sentence boundaries.
    Avoids cutting in the middle of words.
    """
    text = text.strip()
    if not text:
        return []

    if len(text) <= chunk_size:
        return [text]

    # Delimiters in priority order
    delimiters = ["\n\n", "\n", ". ", "? ", "! ", " ", ""]

    def _split_recursive(t: str, current_delimiters: list) -> list:
        if len(t) <= chunk_size or not current_delimiters:
            return [t] if t.strip() else []

        sep = current_delimiters[0]
        remaining_delims = current_delimiters[1:]

        if sep == "":
            # Fallback: slice by characters
            chunks = []
            start = 0
            while start < len(t):
                end = start + chunk_size
                chunks.append(t[start:end])
                start += (chunk_size - chunk_overlap)
            return chunks

        splits = t.split(sep)
        combined_chunks = []
        current_chunk = []
        current_len = 0

        for segment in splits:
            seg_len = len(segment) + (len(sep) if current_chunk else 0)
            if current_len + seg_len > chunk_size and current_chunk:
                merged = sep.join(current_chunk).strip()
                if merged:
                    combined_chunks.append(merged)
                # Keep overlap if possible
                overlap_chars = 0
                overlap_items = []
                for item in reversed(current_chunk):
                    if overlap_chars + len(item) <= chunk_overlap:
                        overlap_items.insert(0, item)
                        overlap_chars += len(item) + len(sep)
                    else:
                        break
                current_chunk = list(overlap_items)
                current_len = sum(len(x) for x in current_chunk) + (len(sep) * (len(current_chunk) - 1) if current_chunk else 0)

            # If a single segment is itself larger than chunk_size, recursively split it
            if len(segment) > chunk_size:
                sub_chunks = _split_recursive(segment, remaining_delims)
                combined_chunks.extend(sub_chunks)
                current_chunk = []
                current_len = 0
            else:
                current_chunk.append(segment)
                current_len += seg_len

        if current_chunk:
            merged = sep.join(current_chunk).strip()
            if merged:
                combined_chunks.append(merged)

        return combined_chunks

    return _split_recursive(text, delimiters)


def chunk_extracted_content(
    extracted_items: List[Dict[str, Any]],
    chunk_size: int = None,
    chunk_overlap: int = None
) -> List[DocumentChunkDTO]:
    """
    Transforms extracted document elements into structured DocumentChunkDTO items.
    
    SPECIAL RULE FOR CSV & XLSX:
    When is_structured_row is True, each individual row represents a complete semantic entity.
    ONE COMPLETE ROW = ONE LOGICAL DOCUMENT CHUNK.
    It is NOT split into arbitrary character slices.
    """
    chunk_size = chunk_size or getattr(settings, 'CHUNK_SIZE', 800)
    chunk_overlap = chunk_overlap or getattr(settings, 'CHUNK_OVERLAP', 100)

    final_chunks = []
    chunk_counter = 0

    for item in extracted_items:
        text = item.get("text", "").strip()
        if not text:
            continue

        page_number = item.get("page_number")
        is_structured_row = item.get("is_structured_row", False)
        base_meta = item.get("metadata", {}).copy()

        # CSV / XLSX special rule: 1 row = 1 semantic chunk
        if is_structured_row:
            final_chunks.append(DocumentChunkDTO(
                content=text,
                chunk_index=chunk_counter,
                page_number=page_number,
                metadata=base_meta
            ))
            chunk_counter += 1
        else:
            # Unstructured text: split with boundary preservation and overlap
            raw_chunks = _split_text_into_chunks(text, chunk_size, chunk_overlap)
            for c in raw_chunks:
                clean_c = c.strip()
                if len(clean_c) > 5:  # skip whitespace/noise
                    final_chunks.append(DocumentChunkDTO(
                        content=clean_c,
                        chunk_index=chunk_counter,
                        page_number=page_number,
                        metadata=base_meta
                    ))
                    chunk_counter += 1

    logger.info(f"Chunking completed: generated {len(final_chunks)} chunks.")
    return final_chunks
