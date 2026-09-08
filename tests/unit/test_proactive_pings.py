import unittest
from unittest.mock import MagicMock, patch

from app.telegram.handler import (
    get_subscribers,
    handle_telegram_update,
    register_subscriber,
    send_medication_reminder_push,
    send_morning_briefing_push,
    send_urgent_email_alert_push,
    unregister_subscriber,
)


class TestProactivePings(unittest.TestCase):

    def setUp(self):
        # Register test chat
        register_subscriber("test_chat_123")

    def tearDown(self):
        unregister_subscriber("test_chat_123")

    def test_subscriber_registration(self):
        register_subscriber("chat_999")
        subs = get_subscribers()
        self.assertIn("chat_999", subs)

        unregister_subscriber("chat_999")
        subs_after = get_subscribers()
        self.assertNotIn("chat_999", subs_after)

    @patch("app.telegram.handler.send_telegram_message")
    @patch("app.telegram.handler.generate_morning_briefing")
    def test_morning_briefing_push(self, mock_briefing, mock_send):
        mock_briefing.return_value = "☀️ Good morning! Today is sunny."
        mock_send.return_value = True

        res = send_morning_briefing_push()
        self.assertEqual(res["status"], "success")
        self.assertGreaterEqual(res["delivered_count"], 1)
        mock_send.assert_called()

    @patch("app.telegram.handler.send_telegram_message")
    @patch("app.telegram.handler.get_today_medication_status")
    def test_medication_reminder_push(self, mock_status, mock_send):
        mock_status.return_value = {
            "items": [
                {"med_name": "Vitamin D", "dosage": "1000 IU", "scheduled_time": "09:00", "status": "pending"}
            ]
        }
        mock_send.return_value = True

        res = send_medication_reminder_push()
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["pending_count"], 1)
        self.assertGreaterEqual(res["delivered_count"], 1)
        mock_send.assert_called()

    @patch("app.telegram.handler.send_telegram_message")
    def test_urgent_email_alert_push(self, mock_send):
        mock_send.return_value = True

        res = send_urgent_email_alert_push(
            subject="Server Down!",
            sender="ops@company.com",
            draft_reply="Investigating immediately.",
        )
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["subject"], "Server Down!")
        self.assertGreaterEqual(res["delivered_count"], 1)
        mock_send.assert_called()

    @patch("app.telegram.handler.send_telegram_message")
    def test_telegram_subscribe_command(self, mock_send):
        mock_send.return_value = True
        update = {
            "message": {
                "chat": {"id": 777888},
                "text": "/subscribe",
            }
        }
        res = handle_telegram_update(update)
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["action"], "subscribed")
        self.assertIn(777888, get_subscribers())

        # Now test unsubscribe
        unsub_update = {
            "message": {
                "chat": {"id": 777888},
                "text": "/unsubscribe",
            }
        }
        unsub_res = handle_telegram_update(unsub_update)
        self.assertEqual(unsub_res["status"], "ok")
        self.assertEqual(unsub_res["action"], "unsubscribed")
        self.assertNotIn(777888, get_subscribers())


if __name__ == "__main__":
    unittest.main()
