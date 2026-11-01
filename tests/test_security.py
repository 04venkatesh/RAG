import uuid
from django.test import TestCase, Client
from django.contrib.auth.models import User
from documents.services import chroma, embedder
from chat.services import retriever
from chat.models import ChatSession, ChatMessage

class SecurityIsolationTests(TestCase):
    """
    CRITICAL SECURITY ACCEPTANCE TEST (Section 95):
    User A uploads secret_a.pdf
    User B uploads secret_b.pdf
    User A asks a question -> ChromaDB must only search user_id = User A.
    User A must NEVER receive User B's chunks under any circumstances.
    """
    def setUp(self):
        self.user_a = User.objects.create_user(username="user_a", password="password_a")
        self.user_b = User.objects.create_user(username="user_b", password="password_b")

        self.doc_a_id = 1001
        self.doc_b_id = 1002

        self.chroma_id_a = f"sec_a_{uuid.uuid4().hex[:8]}"
        self.chroma_id_b = f"sec_b_{uuid.uuid4().hex[:8]}"

        text_a = "Confidential Project Alpha: The master encryption key is ALPHA-SECRET-999."
        text_b = "Confidential Project Beta: The vault unlock combination is BETA-SECRET-888."

        emb_a = embedder.embed_text(text_a)
        emb_b = embedder.embed_text(text_b)

        # Store User A's vector
        chroma.add_chunks(
            ids=[self.chroma_id_a],
            documents=[text_a],
            embeddings=[emb_a],
            metadatas=[{
                "user_id": str(self.user_a.id),
                "document_id": str(self.doc_a_id),
                "document_name": "secret_a.pdf",
                "chunk_index": 0,
                "page_number": 1
            }]
        )

        # Store User B's vector
        chroma.add_chunks(
            ids=[self.chroma_id_b],
            documents=[text_b],
            embeddings=[emb_b],
            metadatas=[{
                "user_id": str(self.user_b.id),
                "document_id": str(self.doc_b_id),
                "document_name": "secret_b.pdf",
                "chunk_index": 0,
                "page_number": 1
            }]
        )

    def tearDown(self):
        try:
            chroma.delete_document_chunks(self.doc_a_id, self.user_a.id)
            chroma.delete_document_chunks(self.doc_b_id, self.user_b.id)
        except Exception:
            pass

    def test_cross_user_vector_isolation(self):
        # User A explicitly searches for Project Beta information
        results_a = retriever.retrieve_relevant_chunks(
            user=self.user_a,
            query="What is the vault unlock combination for Project Beta?",
            top_k=5,
            similarity_threshold=0.0
        )

        for chunk in results_a:
            # User A MUST NEVER see User B's document or content
            self.assertNotEqual(chunk["document_name"], "secret_b.pdf")
            self.assertNotIn("BETA-SECRET-888", chunk["content"])
            self.assertNotEqual(chunk["chunk_id"], self.chroma_id_b)

        # User B explicitly searches for Project Alpha information
        results_b = retriever.retrieve_relevant_chunks(
            user=self.user_b,
            query="What is the master encryption key for Project Alpha?",
            top_k=5,
            similarity_threshold=0.0
        )

        for chunk in results_b:
            # User B MUST NEVER see User A's document or content
            self.assertNotEqual(chunk["document_name"], "secret_a.pdf")
            self.assertNotIn("ALPHA-SECRET-999", chunk["content"])
            self.assertNotEqual(chunk["chunk_id"], self.chroma_id_a)

    def test_cross_user_chat_session_access_forbidden(self):
        # Create chat session belonging to User A
        session_a = ChatSession.objects.create(user=self.user_a, title="User A Private Chat")
        
        # User B logs in and tries to access User A's chat session
        client = Client()
        client.login(username="user_b", password="password_b")

        # GET request to session detail
        response = client.get(f"/chat/{session_a.id}/")
        self.assertEqual(response.status_code, 404)

        # POST request to send message into User A's session
        response_post = client.post(
            f"/chat/{session_a.id}/message/",
            data='{"question": "Can I spy on User A?"}',
            content_type="application/json"
        )
        self.assertEqual(response_post.status_code, 404)
