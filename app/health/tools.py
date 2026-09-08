import uuid
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

MEDICATION_SCHEDULES: list[dict[str, Any]] = []
MEDICATION_LOGS: list[dict[str, Any]] = []


def add_medication_schedule(
    name: str,
    dosage: str = "1 dose",
    times: Optional[list[str]] = None,
    instructions: Optional[str] = None,
    duration_days: Optional[int] = None,
    start_date: Optional[str] = None,
) -> dict[str, Any]:
    """Registers a new medication schedule."""
    if not times:
        times = ["09:00"]
    if not start_date:
        start_date = datetime.now().strftime("%Y-%m-%d")

    schedule = {
        "id": f"med_{uuid.uuid4().hex[:8]}",
        "name": name,
        "dosage": dosage,
        "times": times,
        "instructions": instructions,
        "duration_days": duration_days,
        "start_date": start_date,
        "created_at": datetime.now().isoformat(),
        "active": True,
    }
    MEDICATION_SCHEDULES.append(schedule)
    return {"status": "success", "schedule": schedule}


def log_medication_action(
    med_name: str,
    scheduled_time: str,
    status: str = "taken",
    dosage: str = "1 dose",
) -> dict[str, Any]:
    """Records an adherence action (taken, snoozed, missed) for a medication dose."""
    log_entry = {
        "id": f"log_{uuid.uuid4().hex[:8]}",
        "med_name": med_name,
        "dosage": dosage,
        "scheduled_time": scheduled_time,
        "taken_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": status,
        "timestamp": datetime.now().isoformat(),
    }
    MEDICATION_LOGS.append(log_entry)
    return {"status": "success", "log": log_entry}


def get_today_medication_status(user_timezone: str = "Asia/Kolkata") -> dict[str, Any]:
    """Returns the medication schedule and adherence status for today."""
    try:
        tz = ZoneInfo(user_timezone)
    except Exception:
        tz = ZoneInfo("UTC")

    now = datetime.now(tz)
    today_str = now.strftime("%Y-%m-%d")
    current_hhmm = now.strftime("%H:%M")

    today_items = []
    for med in MEDICATION_SCHEDULES:
        if not med.get("active", True):
            continue

        for scheduled_time in med.get("times", []):
            # Check if this dose was logged today
            logged_entry = None
            for log in reversed(MEDICATION_LOGS):
                if (
                    log["med_name"].lower() == med["name"].lower()
                    and log["scheduled_time"] == scheduled_time
                    and log["taken_time"].startswith(today_str)
                ):
                    logged_entry = log
                    break

            if logged_entry:
                status = logged_entry["status"]
                taken_at = logged_entry["taken_time"].split(" ")[1][:5]
            else:
                status = "upcoming" if scheduled_time > current_hhmm else "pending"
                taken_at = None

            today_items.append({
                "med_name": med["name"],
                "dosage": med.get("dosage", "1 dose"),
                "scheduled_time": scheduled_time,
                "instructions": med.get("instructions"),
                "status": status,
                "taken_at": taken_at,
            })

    # Sort chronologically by scheduled time
    today_items.sort(key=lambda x: x["scheduled_time"])

    # Calculate streak/adherence
    taken_count = sum(1 for item in today_items if item["status"] == "taken")
    total_count = len(today_items)

    return {
        "date": today_str,
        "items": today_items,
        "taken_count": taken_count,
        "total_count": total_count,
        "all_taken": taken_count == total_count and total_count > 0,
    }


def get_all_health_records() -> dict[str, Any]:
    """Returns all medication schedules and adherence logs for synchronization."""
    return {
        "schedules": list(MEDICATION_SCHEDULES),
        "logs": list(MEDICATION_LOGS),
    }


def clear_health_records() -> None:
    """Clears all medication data (for test isolation)."""
    MEDICATION_SCHEDULES.clear()
    MEDICATION_LOGS.clear()
