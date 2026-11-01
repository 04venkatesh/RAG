import os
from django.db import models
from django.contrib.auth.models import User

class Document(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_PROCESSING = 'processing'
    STATUS_PROCESSED = 'processed'
    STATUS_FAILED = 'failed'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_PROCESSING, 'Processing'),
        (STATUS_PROCESSED, 'Processed'),
        (STATUS_FAILED, 'Failed'),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='documents',
        help_text="The owner of this document."
    )
    file = models.FileField(
        upload_to='uploads/%Y/%m/%d/',
        help_text="Path to uploaded document on disk."
    )
    original_filename = models.CharField(
        max_length=255,
        help_text="Original filename as uploaded by the user."
    )
    file_type = models.CharField(
        max_length=50,
        help_text="Normalized file extension e.g. pdf, docx, txt, csv, xlsx."
    )
    file_size = models.PositiveBigIntegerField(
        help_text="File size in bytes."
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True,
        help_text="Current ingestion status."
    )
    error_message = models.TextField(
        blank=True,
        null=True,
        help_text="Detailed error description if processing failed."
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True
    )
    updated_at = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.original_filename} ({self.user.username}) [{self.status}]"

    @property
    def file_size_formatted(self):
        bytes_size = self.file_size
        if bytes_size < 1024:
            return f"{bytes_size} B"
        elif bytes_size < 1024 * 1024:
            return f"{bytes_size / 1024:.1f} KB"
        else:
            return f"{bytes_size / (1024 * 1024):.2f} MB"

    @property
    def chunk_count(self):
        return self.chunks.count()


class DocumentChunk(models.Model):
    """
    PostgreSQL representation of document chunks and metadata.
    IMPORTANT: This model deliberately contains NO VectorField and NO embedding column!
    High-dimensional vector embeddings are stored exclusively in ChromaDB.
    PostgreSQL maintains relational integrity, chunk ordering, and ChromaDB ID mapping.
    """
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name='chunks'
    )
    content = models.TextField(
        help_text="Clean extracted text of this chunk."
    )
    chroma_id = models.CharField(
        max_length=255,
        unique=True,
        db_index=True,
        help_text="Unique identifier linking this chunk to its ChromaDB vector record."
    )
    chunk_index = models.PositiveIntegerField(
        help_text="Zero-based sequence index of the chunk within the document."
    )
    page_number = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Source document page number (1-based), if applicable (e.g. PDF)."
    )
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Flexible metadata (e.g. row_number, sheet_name, headings)."
    )
    created_at = models.DateTimeField(
        auto_now_add=True
    )

    class Meta:
        ordering = ['document', 'chunk_index']
        indexes = [
            models.Index(fields=['document', 'chunk_index']),
        ]

    def __str__(self):
        return f"Doc {self.document_id} Chunk {self.chunk_index} (Chroma: {self.chroma_id})"
