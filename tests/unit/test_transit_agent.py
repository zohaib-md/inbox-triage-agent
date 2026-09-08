import unittest
from unittest.mock import MagicMock, patch

from app.telegram.handler import handle_telegram_update
from app.transit.agent import (
    generate_travel_calendar_url,
    track_flight_status,
    track_train_status,
)


class TestTransitAgent(unittest.TestCase):

    def test_generate_travel_calendar_url(self):
        url = generate_travel_calendar_url(
            title="Flight 6E 204",
            location="Lucknow Airport",
            details="Seat 12A",
        )
        self.assertIn("calendar.google.com", url)
        self.assertIn("Flight+6E+204", url)
        self.assertIn("Lucknow+Airport", url)

    def test_track_flight_status_fallback(self):
        # Even without Vertex AI connection in unit tests, fallback should be clean
        res = track_flight_status("6E 204", user_location="Lucknow")
        self.assertIn("status", res)
        self.assertIn("6E 204", res["identifier"])
        self.assertIn("formatted_reply", res)
        self.assertIn("refresh_callback", res)
        self.assertIn("6E204", res["refresh_callback"])

    def test_track_train_status_pnr(self):
        pnr_text = "My PNR is 2839182910 for Lucknow journey"
        res = track_train_status(pnr_text, user_location="Lucknow")
        self.assertEqual(res["mode"], "pnr")
        self.assertEqual(res["identifier"], "2839182910")
        self.assertIn("confirmtkt.com/pnr-status/2839182910", res["direct_check_url"])
        self.assertIn("2839182910", res["formatted_reply"])

    def test_track_train_status_train_number(self):
        res = track_train_status("12004", user_location="Lucknow")
        self.assertIn("status", res)
        self.assertIn("12004", res["identifier"])
        self.assertIn("refresh_callback", res)
        self.assertIn("12004", res["refresh_callback"])


class TestTelegramTransitRouting(unittest.TestCase):

    @patch("app.telegram.handler.send_telegram_message")
    def test_flight_command(self, mock_send):
        mock_send.return_value = True
        update = {
            "message": {
                "chat": {"id": 12345},
                "text": "/flight 6E 204",
            }
        }
        res = handle_telegram_update(update)
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["action"], "flight_tracked")
        mock_send.assert_called_once()
        args, kwargs = mock_send.call_args
        self.assertIn("6E 204", args[1])
        self.assertIn("inline_keyboard", kwargs["reply_markup"])

    @patch("app.telegram.handler.send_telegram_message")
    def test_train_command(self, mock_send):
        mock_send.return_value = True
        update = {
            "message": {
                "chat": {"id": 12345},
                "text": "/train 12004 Lucknow Shatabdi",
            }
        }
        res = handle_telegram_update(update)
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["action"], "train_tracked")
        mock_send.assert_called_once()
        args, kwargs = mock_send.call_args
        self.assertIn("12004", args[1])

    @patch("app.telegram.handler.send_telegram_message")
    def test_pnr_command(self, mock_send):
        mock_send.return_value = True
        update = {
            "message": {
                "chat": {"id": 12345},
                "text": "/pnr 2839182910",
            }
        }
        res = handle_telegram_update(update)
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["action"], "pnr_tracked")
        mock_send.assert_called_once()
        args, kwargs = mock_send.call_args
        self.assertIn("2839182910", args[1])

    @patch("app.telegram.handler.edit_telegram_message")
    @patch("app.telegram.handler.answer_callback_query")
    def test_transit_refresh_callback(self, mock_ack, mock_edit):
        mock_ack.return_value = True
        mock_edit.return_value = True
        update = {
            "callback_query": {
                "id": "cq_999",
                "data": "refresh_transit:flight:6E204",
                "message": {
                    "chat": {"id": 12345},
                    "message_id": 888,
                },
            }
        }
        res = handle_telegram_update(update)
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["action"], "transit_refreshed_flight")
        mock_ack.assert_called_once()
        mock_edit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
