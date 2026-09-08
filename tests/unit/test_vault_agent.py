import os
import unittest
from unittest.mock import MagicMock, patch

from app.telegram.handler import handle_telegram_update
from app.vault.agent import (
    format_docs_list,
    ingest_document,
    list_vaulted_documents,
    query_vault,
)


class TestVaultAgent(unittest.TestCase):

    def setUp(self):
        sample_bytes = b"%PDF-1.4 sample test content for medical lab test Vitamin B12 and HbA1c"
        ingest_document(
            file_bytes=sample_bytes,
            filename="Blood_Test_Report_July.pdf",
            mime_type="application/pdf",
        )

    def test_ingest_document_fallback(self):
        sample_bytes = b"%PDF-1.4 sample test content for medical lab test Vitamin B12 and HbA1c"
        res = ingest_document(
            file_bytes=sample_bytes,
            filename="Blood_Test_Report_July.pdf",
            mime_type="application/pdf",
        )
        self.assertEqual(res["status"], "success")
        self.assertIn("doc_id", res)
        self.assertEqual(res["filename"], "Blood_Test_Report_July.pdf")
        self.assertIn("formatted_reply", res)
        self.assertIn("Blood_Test_Report_July.pdf", res["formatted_reply"])

    def test_list_vaulted_documents(self):
        docs = list_vaulted_documents()
        self.assertIsInstance(docs, list)
        self.assertTrue(len(docs) >= 1)

    def test_format_docs_list(self):
        docs_text = format_docs_list()
        self.assertIn("Document Vault", docs_text)
        self.assertIn("Blood_Test_Report_July.pdf", docs_text)

    def test_query_vault_with_data(self):
        res = query_vault("What was my Vitamin B12 result?")
        self.assertEqual(res["status"], "success")
        self.assertIn("formatted_reply", res)
        self.assertIn("Blood_Test_Report_July.pdf", res["formatted_reply"])


class TestTelegramVaultRouting(unittest.TestCase):

    @patch("app.telegram.handler.download_telegram_file")
    @patch("app.telegram.handler.send_telegram_message")
    def test_telegram_document_upload(self, mock_send, mock_download):
        mock_send.return_value = True
        mock_download.return_value = b"%PDF-1.4 Star Health Insurance Policy 2026"

        update = {
            "message": {
                "chat": {"id": 888999},
                "document": {
                    "file_id": "file_pdf_123",
                    "file_name": "Star_Health_Policy.pdf",
                    "mime_type": "application/pdf",
                },
            }
        }
        res = handle_telegram_update(update)
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["action"], "document_vaulted")
        mock_download.assert_called_once_with("file_pdf_123")
        self.assertTrue(mock_send.call_count >= 1)

    @patch("app.telegram.handler.download_telegram_file")
    @patch("app.telegram.handler.send_telegram_message")
    def test_telegram_photo_upload(self, mock_send, mock_download):
        mock_send.return_value = True
        mock_download.return_value = b"\xff\xd8\xff image jpeg bytes"

        update = {
            "message": {
                "chat": {"id": 888999},
                "photo": [
                    {"file_id": "p_small", "file_size": 100},
                    {"file_id": "p_large", "file_size": 5000},
                ],
                "caption": "Prescription_Dr_Sharma",
            }
        }
        res = handle_telegram_update(update)
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["action"], "photo_vaulted")
        mock_download.assert_called_once_with("p_large")

    @patch("app.telegram.handler.send_telegram_message")
    def test_telegram_docs_command(self, mock_send):
        mock_send.return_value = True
        update = {
            "message": {
                "chat": {"id": 888999},
                "text": "/docs",
            }
        }
        res = handle_telegram_update(update)
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["action"], "sent_docs_list")
        mock_send.assert_called_once()

    @patch("app.telegram.handler.send_telegram_message")
    def test_telegram_vault_command(self, mock_send):
        mock_send.return_value = True
        update = {
            "message": {
                "chat": {"id": 888999},
                "text": "/vault What is my insurance policy number?",
            }
        }
        res = handle_telegram_update(update)
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["action"], "vault_queried")
        mock_send.assert_called_once()


if __name__ == "__main__":
    unittest.main()
