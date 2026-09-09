import json
import logging
import os
from typing import Any, Optional
from app.voice.schema import CalendarEvent, TodoTask

logger = logging.getLogger("voice_tools")

VOICE_RECORDS_FILE = os.getenv("VOICE_RECORDS_FILE", "/tmp/voice_records.json")
GCS_VAULT_BUCKET = os.getenv("GCS_VAULT_BUCKET", "inbox-triage-vault-507920")

# In-memory cache for calendar events & tasks
CALENDAR_EVENTS: list[dict] = []
TODO_TASKS: list[dict] = []


def _is_testing() -> bool:
    return "PYTEST_CURRENT_TEST" in os.environ or os.getenv("TESTING") == "true"


def _load_persisted_records() -> dict[str, list[dict]]:
    global CALENDAR_EVENTS, TODO_TASKS
    if CALENDAR_EVENTS or TODO_TASKS:
        return {"events": CALENDAR_EVENTS, "tasks": TODO_TASKS}

    # 1. Local cache file
    if os.path.exists(VOICE_RECORDS_FILE):
        try:
            with open(VOICE_RECORDS_FILE, "r") as f:
                data = json.load(f)
                CALENDAR_EVENTS = data.get("events", [])
                TODO_TASKS = data.get("tasks", [])
                return {"events": CALENDAR_EVENTS, "tasks": TODO_TASKS}
        except Exception as e:
            logger.error(f"Error reading local voice records: {e}")

    # 2. Cloud Storage bucket (skip during unit tests)
    if GCS_VAULT_BUCKET and not _is_testing():
        try:
            from google.cloud import storage
            client = storage.Client()
            bucket = client.bucket(GCS_VAULT_BUCKET)
            blob = bucket.blob("voice_records.json")
            if blob.exists():
                data = json.loads(blob.download_as_text())
                CALENDAR_EVENTS = data.get("events", [])
                TODO_TASKS = data.get("tasks", [])
                try:
                    with open(VOICE_RECORDS_FILE, "w") as f:
                        json.dump(data, f, indent=2)
                except Exception:
                    pass
                return {"events": CALENDAR_EVENTS, "tasks": TODO_TASKS}
        except Exception as e:
            logger.warning(f"Could not load voice records from GCS: {e}")

    return {"events": CALENDAR_EVENTS, "tasks": TODO_TASKS}


def _save_persisted_records() -> None:
    data = {
        "events": CALENDAR_EVENTS,
        "tasks": TODO_TASKS,
    }
    try:
        with open(VOICE_RECORDS_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving local voice records: {e}")

    if GCS_VAULT_BUCKET and not _is_testing():
        try:
            from google.cloud import storage
            client = storage.Client()
            bucket = client.bucket(GCS_VAULT_BUCKET)
            blob = bucket.blob("voice_records.json")
            blob.upload_from_string(json.dumps(data, indent=2), content_type="application/json")
        except Exception as e:
            logger.warning(f"Could not sync voice records to GCS: {e}")


def schedule_calendar_event(
    title: str,
    start_time: str,
    end_time: Optional[str] = None,
    location: Optional[str] = None,
    description: Optional[str] = None,
) -> dict:
    """Schedules a calendar event with a title, start time, and optional end time."""
    _load_persisted_records()
    event = {
        "title": title,
        "start_time": start_time,
        "end_time": end_time,
        "location": location,
        "description": description,
    }
    # Avoid exact duplicates
    if not any(e.get("title") == title and e.get("start_time") == start_time for e in CALENDAR_EVENTS):
        CALENDAR_EVENTS.append(event)
        _save_persisted_records()
    return {"status": "success", "message": f"Scheduled '{title}' for {start_time}", "event": event}


def create_todo_task(
    task: str,
    due_date: Optional[str] = None,
    priority: str = "medium",
    category: str = "personal",
) -> dict:
    """Creates an actionable to-do task item with deadline and priority."""
    _load_persisted_records()
    item = {
        "task": task,
        "due_date": due_date,
        "priority": priority,
        "category": category,
    }
    if not any(t.get("task") == task and t.get("due_date") == due_date for t in TODO_TASKS):
        TODO_TASKS.append(item)
        _save_persisted_records()
    return {"status": "success", "message": f"Added task: '{task}' (Priority: {priority})", "task": item}


def get_all_records() -> dict:
    """Returns all stored events and tasks."""
    _load_persisted_records()
    return {
        "events": list(CALENDAR_EVENTS),
        "tasks": list(TODO_TASKS),
    }


def clear_records() -> None:
    """Clears all in-memory records (useful for test isolation)."""
    CALENDAR_EVENTS.clear()
    TODO_TASKS.clear()
    if os.path.exists(VOICE_RECORDS_FILE):
        try:
            os.remove(VOICE_RECORDS_FILE)
        except Exception:
            pass
