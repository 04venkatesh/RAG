import uuid
import time
import logging
from django.db import transaction
from django.utils import timezone
from ..models import Document, DocumentChunk
from . import extractor
from . import chunker
from . import embedder
from . import chroma

logger = logging.getLogger(__name__)

class IngestionError(Exception):
    """Exception raised when document ingestion fails."""
    pass


def process_document(document_id: int) -> bool:
    """
    Executes the complete document ingestion pipeline:
    1. Status -> processing
    2. Text Extraction
    3. Semantic Chunking
    4. Dense Vector Embedding
    5. ChromaDB Vector Storage
    6. PostgreSQL Chunk Persistence
    7. Status -> processed
    
    Includes two-phase rollback logic to ensure PostgreSQL and ChromaDB consistency.
    """
    start_time = time.time()

    try:
        document = Document.objects.get(id=document_id)
    except Document.DoesNotExist:
        logger.error(f"Cannot ingest document: Document with ID {document_id} does not exist.")
        return False

    logger.info(f"--- Starting ingestion for Document {document.id} ('{document.original_filename}') ---")
    document.status = Document.STATUS_PROCESSING
    document.error_message = None
    document.save(update_fields=['status', 'error_message', 'updated_at'])

    file_path = document.file.path
    file_type = document.file_type

    inserted_chroma_ids = []

    try:
        # Step 1: Text Extraction
        logger.info(f"Extracting text from '{document.original_filename}' ({file_type})...")
        extracted_items = extractor.extract_document(file_path, file_type)

        if not extracted_items or not any(item.get("text", "").strip() for item in extracted_items):
            error_msg = "The document contains no extractable text."
            logger.warning(f"Ingestion failed for doc {document.id}: {error_msg}")
            document.status = Document.STATUS_FAILED
            document.error_message = error_msg
            document.save(update_fields=['status', 'error_message', 'updated_at'])
            return False

        logger.info(f"Extracted {len(extracted_items)} elements from '{document.original_filename}'.")

        # Step 2: Semantic Chunking
        chunks = chunker.chunk_extracted_content(extracted_items)
        if not chunks:
            error_msg = "No meaningful chunks could be formed from the extracted content."
            logger.warning(f"Ingestion failed for doc {document.id}: {error_msg}")
            document.status = Document.STATUS_FAILED
            document.error_message = error_msg
            document.save(update_fields=['status', 'error_message', 'updated_at'])
            return False

        logger.info(f"Generated {len(chunks)} chunks for doc {document.id}.")

        # Step 3: Embeddings Generation
        chunk_texts = [c.content for c in chunks]
        logger.info(f"Generating dense embeddings for {len(chunk_texts)} chunks...")
        embeddings = embedder.embed_documents(chunk_texts)

        # Step 4: Prepare ChromaDB records with security and citation metadata
        chroma_ids = []
        chroma_metadatas = []
        for c in chunks:
            # Stable unique UUID-based Chroma ID
            c_id = f"doc_{document.id}_chk_{c.chunk_index}_{uuid.uuid4().hex[:8]}"
            chroma_ids.append(c_id)

            meta = {
                "user_id": str(document.user_id),
                "document_id": str(document.id),
                "document_name": document.original_filename,
                "chunk_index": c.chunk_index,
                "file_type": document.file_type,
            }
            if c.page_number is not None:
                meta["page_number"] = c.page_number
            if "row_number" in c.metadata:
                meta["row_number"] = c.metadata["row_number"]
            if "sheet_name" in c.metadata:
                meta["sheet_name"] = c.metadata["sheet_name"]

            chroma_metadatas.append(meta)

        # Step 5: Store vectors in ChromaDB
        logger.info(f"Inserting {len(chroma_ids)} vectors into ChromaDB...")
        chroma.add_chunks(
            ids=chroma_ids,
            documents=chunk_texts,
            embeddings=embeddings,
            metadatas=chroma_metadatas
        )
        inserted_chroma_ids = chroma_ids

        # Step 6: Store DocumentChunk records in PostgreSQL
        logger.info(f"Saving chunk metadata into PostgreSQL for doc {document.id}...")
        with transaction.atomic():
            # Remove any previous chunks for this document if re-ingesting
            document.chunks.all().delete()

            chunk_records = []
            for c, c_id in zip(chunks, chroma_ids):
                chunk_records.append(
                    DocumentChunk(
                        document=document,
                        content=c.content,
                        chroma_id=c_id,
                        chunk_index=c.chunk_index,
                        page_number=c.page_number,
                        metadata=c.metadata
                    )
                )
            DocumentChunk.objects.bulk_create(chunk_records)

            # Step 7: Mark Document Processed
            document.status = Document.STATUS_PROCESSED
            document.error_message = None
            document.save(update_fields=['status', 'error_message', 'updated_at'])

        elapsed = time.time() - start_time
        logger.info(f"Document {document.id} successfully processed in {elapsed:.2f}s ({len(chunks)} chunks).")
        return True

    except Exception as e:
        logger.exception(f"Unhandled error during ingestion for document {document.id}: {e}")
        # Rollback: Clean up ChromaDB vectors if PostgreSQL failed or exception occurred
        if inserted_chroma_ids:
            try:
                logger.warning(f"Rolling back {len(inserted_chroma_ids)} ChromaDB vectors for document {document.id}...")
                chroma.delete_chunks_by_ids(inserted_chroma_ids)
            except Exception as rollback_err:
                logger.error(f"Failed to rollback ChromaDB vectors: {rollback_err}")

        # Update document status to failed with informative message
        document.status = Document.STATUS_FAILED
        document.error_message = f"Failed to process document: {str(e)}"
        document.save(update_fields=['status', 'error_message', 'updated_at'])
        return False
