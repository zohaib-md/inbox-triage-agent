import unittest
from unittest.mock import patch

from app.calls.agent import _fallback_step_call, _fallback_summarize_call, step_call, summarize_call
from app.calls.schema import CallExtractedData, CallSession, CallStatus, CallTurn
from app.calls.telephony import (
    build_empty_retry_twiml,
    build_gather_twiml,
    build_hangup_twiml,
    complete_call,
    initiate_outbound_call,
    normalize_e164,
    run_simulated_call,
)
from app.calls.tools import (
    clear_call_records,
    list_call_sessions,
    load_call_session,
    save_call_session,
)
from app.voice.tools import clear_records as clear_voice_records
from app.voice.tools import get_all_records as get_voice_records


class TestCallingAgent(unittest.TestCase):
    def setUp(self):
        clear_call_records()
        clear_voice_records()

    def tearDown(self):
        clear_call_records()
        clear_voice_records()

    def test_normalize_e164(self):
        self.assertEqual(normalize_e164("+91 98765-43210"), "+919876543210")
        self.assertEqual(normalize_e164("919876543210"), "+919876543210")
        with self.assertRaises(ValueError):
            normalize_e164("12345")

    def test_twiml_builders(self):
        # 1. Gather TwiML
        gather_xml = build_gather_twiml("Hello from assistant", "sess-123")
        self.assertIn('<Gather action="/calls/respond?session_id=sess-123"', gather_xml)
        self.assertIn('language="en-IN"', gather_xml)
        self.assertIn('voice="Google.en-IN-Wavenet-A"', gather_xml)
        self.assertIn("Hello from assistant", gather_xml)

        # 2. Hangup TwiML
        hangup_xml = build_hangup_twiml("Goodbye!")
        self.assertIn("<Hangup", hangup_xml)
        self.assertIn("Goodbye!", hangup_xml)

        hangup_silent = build_hangup_twiml(None)
        self.assertIn("<Hangup", hangup_silent)
        self.assertNotIn("<Say", hangup_silent)

        # 3. Empty Retry TwiML
        retry_xml = build_empty_retry_twiml("sess-123")
        self.assertIn('<Gather action="/calls/respond?session_id=sess-123"', retry_xml)
        self.assertIn("I didn't quite catch that", retry_xml)

    def test_step_call_fallback(self):
        session = CallSession(
            session_id="test-sess",
            to_number="+919876543210",
            mission="Schedule dentist checkup",
            created_at="2026-09-12T10:00:00",
        )

        # 1. Precomputed greeting on empty input
        res_init = step_call(session, "")
        self.assertFalse(res_init.is_complete)
        self.assertIn("Mohammad Zohaib", res_init.spoken_text)
        self.assertIn("dentist checkup", res_init.spoken_text)

        # 2. In progress inquiry
        res_inq = step_call(session, "Who is calling?")
        self.assertFalse(res_inq.is_complete)

        # 3. Confirmation of slot
        res_confirm = step_call(session, "Yes, 5:30 PM is available today.")
        self.assertTrue(res_confirm.is_complete)
        self.assertIsNotNone(res_confirm.extracted_data)
        self.assertEqual(res_confirm.extracted_data.outcome, "confirmed")
        self.assertIn("17:30:00", res_confirm.extracted_data.start_time)

        # 4. Refusal / no slot
        res_no = step_call(session, "Sorry, we are completely full today.")
        self.assertTrue(res_no.is_complete)
        self.assertEqual(res_no.extracted_data.outcome, "unavailable")

    def test_session_persistence(self):
        session = CallSession(
            session_id="sid-abc",
            to_number="+919876543210",
            mission="Verify reservation",
            call_sid="CA123456789",
            created_at="2026-09-12T10:00:00",
        )
        save_call_session(session)

        # Lookup by session_id
        loaded_by_id = load_call_session("sid-abc")
        self.assertIsNotNone(loaded_by_id)
        self.assertEqual(loaded_by_id.mission, "Verify reservation")

        # Lookup by call_sid
        loaded_by_sid = load_call_session("CA123456789")
        self.assertIsNotNone(loaded_by_sid)
        self.assertEqual(loaded_by_sid.session_id, "sid-abc")

        # Listing
        sessions = list_call_sessions()
        self.assertEqual(len(sessions), 1)

    def test_simulated_call_pipeline(self):
        # Initiate outbound call in simulation mode
        dispatch = initiate_outbound_call(
            to_number="+919876543210",
            mission="Check Dr. Verma availability at 5 PM",
            chat_id=99999,
        )

        self.assertEqual(dispatch.status, "success")
        self.assertEqual(dispatch.mode, "simulated")
        self.assertIsNotNone(dispatch.session_id)

        # Verify session state
        session = load_call_session(dispatch.session_id)
        self.assertIsNotNone(session)
        self.assertEqual(session.status, CallStatus.completed)
        self.assertIsNotNone(session.summary)
        self.assertGreater(len(session.transcript), 2)

        # Verify calendar event auto-scheduled in voice records
        records = get_voice_records()
        self.assertGreaterEqual(len(records["events"]), 1)
        event = records["events"][0]
        self.assertIn("17:30:00", event["start_time"])
        self.assertIn("Dr. Verma", event["title"])

        # Verify complete_call idempotency
        initial_summary = session.summary
        complete_call(session)
        self.assertEqual(session.summary, initial_summary)
        # Should not duplicate calendar event
        self.assertEqual(len(get_voice_records()["events"]), 1)

    def test_complete_call_preserves_failure_status(self):
        session = CallSession(
            session_id="fail-sess",
            to_number="+919876543210",
            mission="Test failed call",
            status=CallStatus.busy,
            created_at="2026-09-12T10:00:00",
        )
        save_call_session(session)

        # complete_call must not overwrite 'busy' with 'completed'
        complete_call(session)
        self.assertEqual(session.status, CallStatus.busy)
        self.assertIn("busy", session.summary.lower())

    def test_api_endpoints_pipeline(self):
        from fastapi.testclient import TestClient
        from app.fast_api_app import app

        client = TestClient(app)

        # 1. Dispatch
        disp_res = client.post(
            "/calls/dispatch",
            json={"to_number": "+91 98765 43210", "mission": "Book dental appointment"},
        )
        self.assertEqual(disp_res.status_code, 200)
        disp_data = disp_res.json()
        self.assertEqual(disp_data["status"], "success")
        self.assertEqual(disp_data["mode"], "simulated")
        sess_id = disp_data["session_id"]

        # 2. History & Session detail
        hist_res = client.get("/calls/history")
        self.assertEqual(hist_res.status_code, 200)
        self.assertGreaterEqual(len(hist_res.json()["calls"]), 1)

        detail_res = client.get(f"/calls/session/{sess_id}")
        self.assertEqual(detail_res.status_code, 200)
        self.assertEqual(detail_res.json()["session_id"], sess_id)

        # 3. TwiML Pickup (form-encoded)
        test_session = CallSession(
            session_id="twiml-sess-1",
            to_number="+919876543210",
            mission="Test clinic inquiry",
            status=CallStatus.initiated,
            created_at="2026-09-12T10:00:00",
            transcript=[
                CallTurn(
                    speaker="ai",
                    text="Hello! Calling on behalf of Mohammad Zohaib for clinic inquiry.",
                    timestamp="2026-09-12T10:00:00",
                )
            ],
        )
        save_call_session(test_session)

        twiml_res = client.post(
            "/calls/twiml?session_id=twiml-sess-1",
            data={"CallSid": "CA999888"},
        )
        self.assertEqual(twiml_res.status_code, 200)
        self.assertIn("application/xml", twiml_res.headers["content-type"])
        self.assertIn("Hello! Calling on behalf of Mohammad Zohaib", twiml_res.text)
        self.assertIn('<Gather action="/calls/respond?session_id=twiml-sess-1"', twiml_res.text)

        # 4. Respond webhook (form-encoded)
        respond_res = client.post(
            "/calls/respond?session_id=twiml-sess-1",
            data={"SpeechResult": "Yes, 5:30 PM is available today", "CallSid": "CA999888"},
        )
        self.assertEqual(respond_res.status_code, 200)
        self.assertIn("<Hangup", respond_res.text)

        # 5. Status webhook (form-encoded)
        status_res = client.post(
            "/calls/status?session_id=twiml-sess-1",
            data={
                "CallStatus": "completed",
                "CallDuration": "42",
                "RecordingUrl": "https://api.twilio.com/recordings/RE12345",
                "CallSid": "CA999888",
            },
        )
        self.assertEqual(status_res.status_code, 200)
        self.assertEqual(status_res.json()["status"], "ok")

        final_sess = load_call_session("twiml-sess-1")
        self.assertIsNotNone(final_sess)
        self.assertEqual(final_sess.duration_seconds, 42)
        self.assertEqual(final_sess.recording_url, "https://api.twilio.com/recordings/RE12345")

    @patch("app.telegram.handler.send_telegram_message")
    def test_telegram_call_routing(self, mock_send_msg):
        from app.telegram.handler import handle_telegram_update

        mock_send_msg.return_value = True

        # 1. Test /call command
        update_cmd = {
            "message": {
                "chat": {"id": 123456},
                "text": "/call +919876543210 Check Dr. Verma clinic availability today",
            }
        }
        res_cmd = handle_telegram_update(update_cmd)
        self.assertEqual(res_cmd["status"], "ok")
        self.assertEqual(res_cmd["action"], "call_initiated")
        self.assertIsNotNone(res_cmd["session_id"])

        # Check that dispatch card was sent before completion debrief
        self.assertGreaterEqual(mock_send_msg.call_count, 2)
        first_call_text = mock_send_msg.call_args_list[0][1]["text"] if "text" in mock_send_msg.call_args_list[0][1] else mock_send_msg.call_args_list[0][0][1]
        self.assertIn("Initiating Outbound Phone Call", first_call_text)

        # 2. Test natural text intent "call +..."
        mock_send_msg.reset_mock()
        update_text = {
            "message": {
                "chat": {"id": 123456},
                "text": "call +91 98765 43210 Reserve table for 2 at 8 PM",
            }
        }
        res_text = handle_telegram_update(update_text)
        self.assertEqual(res_text["status"], "ok")
        self.assertEqual(res_text["action"], "call_initiated")
        self.assertIsNotNone(res_text["session_id"])


if __name__ == "__main__":
    unittest.main()
