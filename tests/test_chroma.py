import uuid
from django.test import TestCase
from documents.services import chroma, embedder

class ChromaServiceTests(TestCase):
    def setUp(self):
        self.test_user_id = 9999
        self.test_doc_id = 8888
        self.c_id = f"test_chk_{uuid.uuid4().hex[:8]}"

    def tearDown(self):
        try:
            chroma.delete_document_chunks(self.test_doc_id, self.test_user_id)
        except Exception:
            pass

    def test_collection_creation_and_cosine_space(self):
        coll = chroma.get_collection()
        self.assertIsNotNone(coll)
        # Cosine space metadata verification
        metadata = coll.metadata or {}
        self.assertEqual(metadata.get("hnsw:space"), "cosine")

    def test_add_and_query_with_user_filter(self):
        text = "Django and ChromaDB work harmoniously in local RAG architectures."
        emb = embedder.embed_text(text)
        
        chroma.add_chunks(
            ids=[self.c_id],
            documents=[text],
            embeddings=[emb],
            metadatas=[{
                "user_id": str(self.test_user_id),
                "document_id": str(self.test_doc_id),
                "document_name": "architecture.txt",
                "chunk_index": 0,
                "page_number": 1
            }]
        )

        # Query with user filter
        results = chroma.query_chunks(
            query_embedding=emb,
            user_id=self.test_user_id,
            n_results=1
        )

        matched_ids = results.get("ids", [[]])[0]
        self.assertIn(self.c_id, matched_ids)

        # Query with different user ID should return NOTHING
        other_results = chroma.query_chunks(
            query_embedding=emb,
            user_id=1234567, # Other user
            n_results=1
        )
        self.assertEqual(len(other_results.get("ids", [[]])[0]), 0)

    def test_delete_document_chunks(self):
        text = "This document chunk should be deleted."
        emb = embedder.embed_text(text)

        chroma.add_chunks(
            ids=[self.c_id],
            documents=[text],
            embeddings=[emb],
            metadatas=[{
                "user_id": str(self.test_user_id),
                "document_id": str(self.test_doc_id),
                "document_name": "delete_me.txt",
                "chunk_index": 0
            }]
        )

        deleted_count = chroma.delete_document_chunks(self.test_doc_id, self.test_user_id)
        self.assertGreaterEqual(deleted_count, 1)

        # Verify no vectors remain
        results = chroma.query_chunks(
            query_embedding=emb,
            user_id=self.test_user_id,
            n_results=5
        )
        self.assertEqual(len(results.get("ids", [[]])[0]), 0)
