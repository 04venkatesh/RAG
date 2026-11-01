from unittest.mock import patch
from django.test import TestCase
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from documents.models import Document
from documents.services import ingestion, chroma
from chat.models import ChatSession, ChatMessage
from chat.services import rag

class RAGPipelineTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="rag_tester", password="password123")
        self.session = ChatSession.objects.create(user=self.user, title="RAG Test Session")

        # Ingest test document (Section 96)
        content = (
            "The company was founded in 2015. "
            "The company has 500 employees. "
            "The headquarters is in Chennai."
        ).encode("utf-8")

        uploaded = SimpleUploadedFile("company_profile.txt", content, content_type="text/plain")
        self.doc = Document.objects.create(
            user=self.user,
            file=uploaded,
            original_filename="company_profile.txt",
            file_type="txt",
            file_size=len(content),
            status=Document.STATUS_PENDING
        )
        ingestion.process_document(self.doc.id)

    def tearDown(self):
        try:
            chroma.delete_document_chunks(self.doc.id, self.user.id)
        except Exception:
            pass

    @patch('chat.services.llm.generate')
    def test_rag_pipeline_with_factual_retrieval(self, mock_generate):
        mock_generate.return_value = "According to the uploaded document, the company was founded in 2015."

        result = rag.answer_question(
            user=self.user,
            question="When was the company founded?",
            session=self.session,
            similarity_threshold=0.30
        )

        self.assertIn("founded in 2015", result["answer"])
        self.assertGreaterEqual(len(result["sources"]), 1)
        self.assertEqual(result["sources"][0]["document_name"], "company_profile.txt")
        self.assertTrue(mock_generate.called)

    def test_rag_quality_controlled_fallback_when_unrelated(self):
        """
        SECTION 40 & 96:
        If no retrieved chunk passes the configured relevance threshold,
        do not ask Mistral to invent an answer. Return controlled fallback.
        """
        result = rag.answer_question(
            user=self.user,
            question="What is the quantum spin of a muon in particle physics?",
            session=self.session,
            similarity_threshold=0.85 # Strict threshold to simulate weak relevance
        )

        self.assertEqual(
            result["answer"],
            "I couldn't find enough relevant information in your uploaded documents to answer that question."
        )
        self.assertEqual(len(result["sources"]), 0)

    @patch('chat.services.llm.generate')
    def test_conversation_history_passed_to_prompt(self, mock_generate):
        mock_generate.return_value = "The advantages include high accuracy and scalability."

        # Add existing conversation turns
        ChatMessage.objects.create(session=self.session, role='user', content="What is supervised learning?")
        ChatMessage.objects.create(session=self.session, role='assistant', content="Supervised learning trains models on labeled data.")

        # Follow-up question
        result = rag.answer_question(
            user=self.user,
            question="What are its advantages?",
            session=self.session,
            similarity_threshold=0.0 # Force retrieval for test
        )

        # Inspect prompt passed to mock_generate
        call_args = mock_generate.call_args[0][0]
        self.assertIn("What is supervised learning?", call_args)
        self.assertIn("Supervised learning trains models on labeled data.", call_args)
        self.assertIn("What are its advantages?", call_args)
