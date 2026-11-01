from django.test import TestCase
from documents.services.chunker import chunk_extracted_content, _split_text_into_chunks

class ChunkingServiceTests(TestCase):
    def test_text_splitting_boundaries_and_overlap(self):
        text = "First paragraph with introductory context.\n\nSecond paragraph discussing important details.\n\nThird paragraph."
        chunks = _split_text_into_chunks(text, chunk_size=50, chunk_overlap=10)
        self.assertTrue(len(chunks) >= 2)
        # Verify no words are arbitrarily cut if possible
        for c in chunks:
            self.assertTrue(len(c) <= 65) # slight leeway for word boundary

    def test_page_preservation_for_unstructured_content(self):
        extracted = [
            {"page_number": 1, "text": "This is content from page 1 of the report.", "is_structured_row": False},
            {"page_number": 2, "text": "This is content from page 2 of the report.", "is_structured_row": False}
        ]
        chunks = chunk_extracted_content(extracted, chunk_size=200, chunk_overlap=20)
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0].page_number, 1)
        self.assertEqual(chunks[1].page_number, 2)

    def test_special_csv_xlsx_chunking_rule_one_row_one_chunk(self):
        """
        SPECIAL RULE FOR STRUCTURED DATASETS (Section 26):
        For CSV/XLSX rows where each row represents one complete semantic entity,
        ONE COMPLETE ROW = ONE LOGICAL DOCUMENT CHUNK.
        It must not be arbitrarily split by character count.
        """
        extracted_rows = [
            {
                "page_number": None,
                "text": "Company: ABC Technologies\nIndustry: Software\nLocation: Chennai\nEmployees: 500\nRevenue: 10 million",
                "is_structured_row": True,
                "metadata": {"row_number": 1, "sheet_name": "Enterprises"}
            },
            {
                "page_number": None,
                "text": "Company: XYZ Innovations\nIndustry: Artificial Intelligence\nLocation: Coimbatore\nEmployees: 120\nRevenue: 4 million",
                "is_structured_row": True,
                "metadata": {"row_number": 2, "sheet_name": "Enterprises"}
            }
        ]

        chunks = chunk_extracted_content(extracted_rows, chunk_size=50) # chunk_size is intentionally smaller than text
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0].chunk_index, 0)
        self.assertEqual(chunks[1].chunk_index, 1)
        self.assertIn("ABC Technologies", chunks[0].content)
        self.assertIn("XYZ Innovations", chunks[1].content)
        self.assertEqual(chunks[0].metadata.get("row_number"), 1)
        self.assertEqual(chunks[1].metadata.get("sheet_name"), "Enterprises")
