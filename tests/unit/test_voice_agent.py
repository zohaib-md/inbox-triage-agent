from unittest.mock import patch

import pytest
from app.telegram.handler import handle_telegram_update
from app.voice.agent import process_voice_or_text
from app.voice.schema import VoiceExtractionResult
from app.voice.tools import clear_records, get_all_records


@pytest.fixture(autouse=True)
def clean_store():
    clear_records()
    yield
    clear_records()


def test_process_voice_or_text_offline_fallback():
    # Test fallback parser when no audio is provided
    result = process_voice_or_text(
        text="Team meeting tomorrow at 3 PM, and buy groceries tonight",
        user_timezone="Asia/Kolkata"
    )
    assert isinstance(result, VoiceExtractionResult)
    assert len(result.events) + len(result.tasks) >= 1

    records = get_all_records()
    assert len(records["events"]) + len(records["tasks"]) >= 1


def test_telegram_start_command():
    fake_update = {
        "message": {
            "chat": {"id": 12345},
            "text": "/start",
        }
    }
    with patch("app.telegram.handler.send_telegram_message", return_value=True) as mock_send:
        resp = handle_telegram_update(fake_update)
        assert resp["status"] == "ok"
        assert resp["action"] == "sent_welcome"
        mock_send.assert_called_once()


def test_telegram_text_task_update():
    fake_update = {
        "message": {
            "chat": {"id": 12345},
            "text": "Dentist appointment tomorrow at 4 PM, and remind me to pay credit card bill by Friday.",
        }
    }
    with patch("app.telegram.handler.send_telegram_message", return_value=True) as mock_send:
        resp = handle_telegram_update(fake_update)
        assert resp["status"] == "ok"
        assert mock_send.call_count == 1
        records = get_all_records()
        assert len(records["events"]) + len(records["tasks"]) >= 1
