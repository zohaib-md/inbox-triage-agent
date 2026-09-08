from unittest.mock import patch
import pytest

from app.search.agent import search_live_web
from app.telegram.handler import handle_telegram_update


def test_search_live_web_fallback():
    # In test environment without Vertex credentials, verify clean fallback structure
    res = search_live_web("best parks in Lucknow", user_location="Lucknow")
    assert "query" in res
    assert "formatted_reply" in res
    assert "best parks in Lucknow" in res["formatted_reply"]
    assert len(res["sources"]) >= 1


def test_telegram_search_command():
    with patch("app.telegram.handler.send_telegram_message", return_value=True) as mock_send:
        # 1. /search without query -> shows help
        update_empty = {
            "message": {
                "chat": {"id": 123},
                "text": "/search",
            }
        }
        res_empty = handle_telegram_update(update_empty)
        assert res_empty["status"] == "ok"
        assert res_empty["action"] == "sent_search_help"

        # 2. /search with query -> runs search
        update_query = {
            "message": {
                "chat": {"id": 123},
                "text": "/search top museums in Lucknow",
            }
        }
        res_query = handle_telegram_update(update_query)
        assert res_query["status"] == "ok"
        assert res_query["action"] == "live_search_performed"
        assert mock_send.call_count == 2


def test_telegram_natural_search_intent():
    with patch("app.telegram.handler.send_telegram_message", return_value=True) as mock_send:
        update_question = {
            "message": {
                "chat": {"id": 123},
                "text": "find best kebabs in Lucknow",
            }
        }
        res = handle_telegram_update(update_question)
        assert res["status"] == "ok"
        assert res["action"] == "live_search_performed"
        mock_send.assert_called_once()
