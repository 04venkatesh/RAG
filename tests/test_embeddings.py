import numpy as np
from django.test import TestCase
from documents.services import embedder

class EmbeddingServiceTests(TestCase):
    def test_embedding_generation_and_dimension(self):
        text = "Retrieval Augmented Generation enables grounding LLMs on local documents."
        vec = embedder.embed_text(text)
        self.assertIsInstance(vec, list)
        dim = embedder.get_embedding_dimension()
        self.assertEqual(len(vec), dim)
        self.assertEqual(dim, 384) # all-MiniLM-L6-v2 produces 384 dimensions

    def test_embeddings_batch_generation(self):
        texts = [
            "Machine learning is transforming data science.",
            "PostgreSQL stores structured relational tables.",
            "ChromaDB stores high-dimensional dense embeddings."
        ]
        vectors = embedder.embed_documents(texts, batch_size=2)
        self.assertEqual(len(vectors), 3)
        for v in vectors:
            self.assertEqual(len(v), 384)

    def test_normalized_embeddings_for_cosine_metric(self):
        vec = embedder.embed_text("Test vector normalization")
        norm = np.linalg.norm(vec)
        self.assertAlmostEqual(norm, 1.0, places=4)
