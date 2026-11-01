import uuid
from django.test import TestCase
from django.contrib.auth.models import User
from documents.services import chroma, embedder
from chat.services import retriever

class RetrievalServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="retrieval_user", password="password123")
        self.doc_id = 7777
        self.c_id1 = f"ret_chk_1_{uuid.uuid4().hex[:8]}"
        self.c_id2 = f"ret_chk_2_{uuid.uuid4().hex[:8]}"

        doc1_text = "Photosynthesis is the process by which green plants use sunlight to synthesize nutrients."
        doc2_text = "The solar panel converts sunlight directly into electricity through the photovoltaic effect."

        emb1 = embedder.embed_text(doc1_text)
        emb2 = embedder.embed_text(doc2_text)

        chroma.add_chunks(
            ids=[self.c_id1, self.c_id2],
            documents=[doc1_text, doc2_text],
            embeddings=[emb1, emb2],
            metadatas=[
                {
                    "user_id": str(self.user.id),
                    "document_id": str(self.doc_id),
                    "document_name": "biology.pdf",
                    "chunk_index": 0,
                    "page_number": 12
                },
                {
                    "user_id": str(self.user.id),
                    "document_id": str(self.doc_id),
                    "document_name": "energy.pdf",
                    "chunk_index": 1,
                    "page_number": 4
                }
            ]
        )

    def tearDown(self):
        try:
            chroma.delete_document_chunks(self.doc_id, self.user.id)
        except Exception:
            pass

    def test_semantic_retrieval_ranking(self):
        query = "How do plants convert sunlight into food?"
        chunks = retriever.retrieve_relevant_chunks(
            user=self.user,
            query=query,
            top_k=2,
            similarity_threshold=0.30
        )
        self.assertGreaterEqual(len(chunks), 1)
        # Top chunk should be biology.pdf regarding plants
        top_chunk = chunks[0]
        self.assertEqual(top_chunk["document_name"], "biology.pdf")
        self.assertEqual(top_chunk["page_number"], 12)
        self.assertIn("Photosynthesis", top_chunk["content"])
        self.assertGreater(top_chunk["score"], 0.5)

    def test_relevance_threshold_filtering(self):
        # Extremely high similarity threshold should filter out unrelated queries
        query = "What is the capital city of France?"
        chunks = retriever.retrieve_relevant_chunks(
            user=self.user,
            query=query,
            top_k=5,
            similarity_threshold=0.90
        )
        self.assertEqual(len(chunks), 0)
