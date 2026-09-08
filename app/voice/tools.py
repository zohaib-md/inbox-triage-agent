from typing import Optional
from app.voice.schema import CalendarEvent, TodoTask

# In-memory storage for calendar events & tasks
CALENDAR_EVENTS: list[dict] = []
TODO_TASKS: list[dict] = []


def schedule_calendar_event(
    title: str,
    start_time: str,
    end_time: Optional[str] = None,
    location: Optional[str] = None,
    description: Optional[str] = None,
) -> dict:
    """Schedules a calendar event with a title, start time, and optional end time."""
    event = {
        "title": title,
        "start_time": start_time,
        "end_time": end_time,
        "location": location,
        "description": description,
    }
    CALENDAR_EVENTS.append(event)
    return {"status": "success", "message": f"Scheduled '{title}' for {start_time}", "event": event}


def create_todo_task(
    task: str,
    due_date: Optional[str] = None,
    priority: str = "medium",
    category: str = "personal",
) -> dict:
    """Creates an actionable to-do task item with deadline and priority."""
    item = {
        "task": task,
        "due_date": due_date,
        "priority": priority,
        "category": category,
    }
    TODO_TASKS.append(item)
    return {"status": "success", "message": f"Added task: '{task}' (Priority: {priority})", "task": item}


def get_all_records() -> dict:
    """Returns all stored events and tasks."""
    return {
        "events": list(CALENDAR_EVENTS),
        "tasks": list(TODO_TASKS),
    }


def clear_records() -> None:
    """Clears all in-memory records (useful for test isolation)."""
    CALENDAR_EVENTS.clear()
    TODO_TASKS.clear()
