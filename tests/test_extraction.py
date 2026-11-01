import io
import os
import tempfile
from django.test import TestCase
from documents.services import extractor

class ExtractionServiceTests(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_extract_txt(self):
        file_path = os.path.join(self.temp_dir, "sample.txt")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("Artificial intelligence is a branch of computer science.")

        items = extractor.extract_document(file_path, "txt")
        self.assertEqual(len(items), 1)
        self.assertIn("Artificial intelligence", items[0]["text"])
        self.assertEqual(items[0]["page_number"], 1)

    def test_extract_csv(self):
        file_path = os.path.join(self.temp_dir, "companies.csv")
        csv_content = (
            "Company,Industry,Headquarters,Employees\n"
            "TechCorp,Software,Bengaluru,1500\n"
            "HealthPlus,Biotech,Hyderabad,800\n"
        )
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(csv_content)

        items = extractor.extract_document(file_path, "csv")
        self.assertEqual(len(items), 2)
        self.assertTrue(items[0]["is_structured_row"])
        self.assertIn("Company: TechCorp", items[0]["text"])
        self.assertIn("Industry: Software", items[0]["text"])
        self.assertIn("Headquarters: Bengaluru", items[0]["text"])
        self.assertIn("Employees: 1500", items[0]["text"])

    def test_extract_pdf(self):
        import fitz
        file_path = os.path.join(self.temp_dir, "document.pdf")
        doc = fitz.open()
        page1 = doc.new_page()
        page1.insert_text((50, 50), "This is page 1 content of the research paper.")
        page2 = doc.new_page()
        page2.insert_text((50, 50), "This is page 2 content detailing experimental results.")
        doc.save(file_path)
        doc.close()

        items = extractor.extract_document(file_path, "pdf")
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["page_number"], 1)
        self.assertIn("page 1 content", items[0]["text"])
        self.assertEqual(items[1]["page_number"], 2)
        self.assertIn("page 2 content", items[1]["text"])

    def test_extract_docx(self):
        import docx
        file_path = os.path.join(self.temp_dir, "report.docx")
        doc = docx.Document()
        doc.add_heading("Project Overview", level=1)
        doc.add_paragraph("This paragraph outlines the primary system objectives.")
        table = doc.add_table(rows=2, cols=2)
        table.rows[0].cells[0].text = "Metric"
        table.rows[0].cells[1].text = "Value"
        table.rows[1].cells[0].text = "Accuracy"
        table.rows[1].cells[1].text = "98.5%"
        doc.save(file_path)

        items = extractor.extract_document(file_path, "docx")
        self.assertEqual(len(items), 1)
        text = items[0]["text"]
        self.assertIn("Project Overview", text)
        self.assertIn("primary system objectives", text)
        self.assertIn("Metric", text)
        self.assertIn("Accuracy", text)
        self.assertIn("98.5%", text)

    def test_extract_xlsx(self):
        import openpyxl
        file_path = os.path.join(self.temp_dir, "data.xlsx")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Employees"
        ws.append(["ID", "Name", "Role", "Department"])
        ws.append([101, "Alice Smith", "Engineer", "R&D"])
        ws.append([102, "Bob Jones", "Analyst", "Finance"])
        wb.save(file_path)
        wb.close()

        items = extractor.extract_document(file_path, "xlsx")
        self.assertEqual(len(items), 2)
        self.assertTrue(items[0]["is_structured_row"])
        self.assertIn("Sheet: Employees", items[0]["text"])
        self.assertIn("Name: Alice Smith", items[0]["text"])
        self.assertIn("Role: Engineer", items[0]["text"])
        self.assertIn("Department: R&D", items[0]["text"])
