from unittest.mock import patch
import pytest

from app.briefing.briefing_agent import generate_morning_briefing
from app.briefing.weather import get_current_weather
from app.health.agent import process_medication_intake
from app.health.tools import (
    add_medication_schedule,
    clear_health_records,
    get_today_medication_status,
    log_medication_action,
)
from app.telegram.handler import handle_telegram_update


@pytest.fixture(autouse=True)
def clean_stores():
    clear_health_records()
    yield
    clear_health_records()


def test_medication_tools():
    # 1. Add medication
    res = add_medication_schedule(
        name="Vitamin D3",
        dosage="1000 IU",
        times=["09:00"],
        instructions="after breakfast",
        duration_days=30,
    )
    assert res["status"] == "success"

    # 2. Check today status before taking
    status = get_today_medication_status()
    assert status["total_count"] == 1
    assert status["taken_count"] == 0

    # 3. Log action
    log_res = log_medication_action(med_name="Vitamin D3", scheduled_time="09:00", status="taken")
    assert log_res["status"] == "success"

    # 4. Check today status after taking
    status_after = get_today_medication_status()
    assert status_after["taken_count"] == 1
    assert status_after["all_taken"] is True


def test_process_medication_intake_fallback():
    result = process_medication_intake(text="Amoxicillin 500mg twice a day for 7 days")
    assert len(result.medications) >= 1
    assert result.medications[0].name.lower() == "amoxicillin"
    assert len(result.medications[0].times) == 2


def test_weather_and_morning_briefing():
    weather = get_current_weather()
    assert "city" in weather
    assert "temperature" in weather

    briefing = generate_morning_briefing(user_name="Zohaib")
    assert "Good morning, Zohaib!" in briefing
    assert "Weather:" in briefing
    assert "Today's Schedule:" in briefing


def test_telegram_briefing_and_meds_commands():
    with patch("app.telegram.handler.send_telegram_message", return_value=True) as mock_send:
        # /briefing
        res1 = handle_telegram_update({"message": {"chat": {"id": 123}, "text": "/briefing"}})
        assert res1["status"] == "ok"
        assert res1["action"] == "sent_briefing"
        assert mock_send.call_count == 1

        # /meds
        res2 = handle_telegram_update({"message": {"chat": {"id": 123}, "text": "/meds"}})
        assert res2["status"] == "ok"
        assert mock_send.call_count == 2


def test_telegram_callback_taken():
    with patch("app.telegram.handler.answer_callback_query", return_value=True) as mock_answer:
        with patch("app.telegram.handler.edit_telegram_message", return_value=True) as mock_edit:
            cb_update = {
                "callback_query": {
                    "id": "cq_123",
                    "data": "take_med:Amoxicillin:09:00",
                    "message": {
                        "chat": {"id": 123},
                        "message_id": 456,
                    },
                }
            }
            res = handle_telegram_update(cb_update)
            assert res["status"] == "ok"
            assert res["action"] == "med_taken_logged"
            mock_answer.assert_called_once()
            mock_edit.assert_called_once()
