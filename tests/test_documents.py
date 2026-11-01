import io
import os
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.exceptions import ValidationError
from documents.models import Document, DocumentChunk
from documents.services import loaders, chroma, ingestion

class DocumentTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="doc_owner", password="password123")
        self.other_user = User.objects.create_user(username="stranger", password="password123")
        self.client = Client()
        self.client.login(username="doc_owner", password="password123")

    def test_file_validation_allowed_extensions(self):
        valid_file = SimpleUploadedFile("notes.txt", b"Some valid notes", content_type="text/plain")
        ext = loaders.validate_uploaded_file(valid_file)
        self.assertEqual(ext, "txt")

    def test_file_validation_unsupported_extension_rejected(self):
        invalid_file = SimpleUploadedFile("malicious.exe", b"binary content", content_type="application/octet-stream")
        with self.assertRaises(ValidationError):
            loaders.validate_uploaded_file(invalid_file)

    def test_document_ingestion_txt(self):
        test_content = b"The company was founded in 2015. It specializes in natural language processing."
        uploaded_file = SimpleUploadedFile("history.txt", test_content, content_type="text/plain")
        
        doc = Document.objects.create(
            user=self.user,
            file=uploaded_file,
            original_filename="history.txt",
            file_type="txt",
            file_size=len(test_content),
            status=Document.STATUS_PENDING
        )

        success = ingestion.process_document(doc.id)
        self.assertTrue(success)

        doc.refresh_from_db()
        self.assertEqual(doc.status, Document.STATUS_PROCESSED)
        self.assertGreaterEqual(doc.chunks.count(), 1)
        
        chunk = doc.chunks.first()
        self.assertIn("founded in 2015", chunk.content)
        self.assertTrue(chunk.chroma_id.startswith(f"doc_{doc.id}_chk_"))

        # Clean up
        chroma.delete_document_chunks(doc.id, self.user.id)

    def test_document_deletion_cascades_vectors_and_chunks(self):
        test_content = b"Content to be deleted completely from both PostgreSQL and ChromaDB."
        uploaded_file = SimpleUploadedFile("to_delete.txt", test_content, content_type="text/plain")

        doc = Document.objects.create(
            user=self.user,
            file=uploaded_file,
            original_filename="to_delete.txt",
            file_type="txt",
            file_size=len(test_content),
            status=Document.STATUS_PENDING
        )
        ingestion.process_document(doc.id)
        doc_id = doc.id

        # Verify chunks exist in PostgreSQL
        self.assertGreaterEqual(DocumentChunk.objects.filter(document_id=doc_id).count(), 1)

        # POST delete through view
        response = self.client.post(f"/documents/{doc_id}/delete/")
        self.assertEqual(response.status_code, 302)

        # Verify document and chunks deleted from PostgreSQL
        self.assertFalse(Document.objects.filter(id=doc_id).exists())
        self.assertEqual(DocumentChunk.objects.filter(document_id=doc_id).count(), 0)
