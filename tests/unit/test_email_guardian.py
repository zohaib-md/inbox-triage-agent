import unittest
from unittest.mock import MagicMock, patch

from app.telegram.handler import (
    get_pending_draft_sends,
    handle_telegram_update,
    mark_draft_sent,
    queue_approved_draft,
    register_subscriber,
    send_urgent_email_alert_push,
    unregister_subscriber,
)


class TestEmailGuardian(unittest.TestCase):

    def setUp(self):
        register_subscriber("tg_chat_111")

    def tearDown(self):
        unregister_subscriber("tg_chat_111")

    @patch("app.telegram.handler.send_telegram_message")
    def test_send_urgent_email_alert_with_button(self, mock_send):
        mock_send.return_value = True

        res = send_urgent_email_alert_push(
            subject="Critical: Production Incident",
            sender="cto@startup.com",
            draft_reply="On it right now. Investigating logs.",
            draft_id="draft_abc_123",
            thread_id="thread_xyz_999",
        )
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["draft_id"], "draft_abc_123")
        mock_send.assert_called()

        # Verify that our test chat was sent the message with the inline buttons
        found_test_chat = False
        for call in mock_send.call_args_list:
            args, kwargs = call
            if args[0] == "tg_chat_111":
                found_test_chat = True
                self.assertIn("Critical: Production Incident", args[1])
                self.assertIn("cto@startup.com", args[1])
                self.assertIn("reply_markup", kwargs)
                buttons = kwargs["reply_markup"]["inline_keyboard"]
                self.assertEqual(buttons[0][0]["callback_data"], "send_email_draft:draft_abc_123")
                self.assertEqual(buttons[1][0]["callback_data"], "dismiss_email:draft_abc_123")

        self.assertTrue(found_test_chat)

    @patch("app.telegram.handler.edit_telegram_message")
    @patch("app.telegram.handler.answer_callback_query")
    def test_send_email_draft_callback(self, mock_ack, mock_edit):
        mock_ack.return_value = True
        mock_edit.return_value = True

        update = {
            "callback_query": {
                "id": "cq_email_123",
                "data": "send_email_draft:draft_test_777",
                "message": {
                    "chat": {"id": "tg_chat_111"},
                    "message_id": 555,
                },
            }
        }
        res = handle_telegram_update(update)
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["action"], "email_draft_approved")
        self.assertEqual(res["draft_id"], "draft_test_777")
        mock_ack.assert_called_once()
        mock_edit.assert_called_once()

        # Check that it appears in pending draft sends
        pending = get_pending_draft_sends()
        matching = [d for d in pending if d.get("draft_id") == "draft_test_777"]
        self.assertTrue(len(matching) >= 1)

    @patch("app.telegram.handler.edit_telegram_message")
    def test_mark_draft_sent(self, mock_edit):
        mock_edit.return_value = True

        queue_approved_draft(
            draft_id="draft_sent_test_888",
            metadata={
                "chat_id": "tg_chat_111",
                "message_id": 666,
                "sender": "investor@fund.com",
                "subject": "Term Sheet Follow-up",
            }
        )
        success = mark_draft_sent("draft_sent_test_888")
        self.assertTrue(success)
        mock_edit.assert_called_once()
        args, _ = mock_edit.call_args
        self.assertIn("Email Reply Sent", args[2])
        self.assertIn("investor@fund.com", args[2])


if __name__ == "__main__":
    unittest.main()
