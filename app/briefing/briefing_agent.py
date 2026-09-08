from datetime import datetime
from zoneinfo import ZoneInfo

from app.briefing.weather import get_current_weather
from app.health.tools import get_today_medication_status
from app.voice.tools import CALENDAR_EVENTS, TODO_TASKS


def generate_morning_briefing(user_timezone: str = "Asia/Kolkata", user_name: str = "Zohaib") -> str:
    """Compiles the daily 8:00 AM executive secretary briefing."""
    try:
        tz = ZoneInfo(user_timezone)
    except Exception:
        tz = ZoneInfo("UTC")

    now = datetime.now(tz)
    date_header = now.strftime("%A, %B %d, %Y")
    today_prefix = now.strftime("%Y-%m-%d")

    # 1. Weather
    weather = get_current_weather()


    # 2. Today's Calendar Events
    today_events = [
        ev for ev in CALENDAR_EVENTS
        if ev.get("start_time", "").startswith(today_prefix)
    ]

    # 3. Today's Medications
    med_status = get_today_medication_status(user_timezone=user_timezone)
    med_items = med_status.get("items", [])

    # 4. Top Tasks
    pending_tasks = [tk for tk in TODO_TASKS if tk.get("priority") in ["high", "medium"]][:3]

    lines = [
        f"☀️ *Good morning, {user_name}!*",
        f"📅 *{date_header}*",
        "",
        f"🌤️ *Weather:* {weather['summary']} (Humidity: {weather['humidity']})",
        "",
    ]

    # Calendar section
    lines.append("📅 *Today's Schedule:*")
    if today_events:
        for ev in today_events:
            time_part = ev["start_time"].split("T")[1][:5] if "T" in ev["start_time"] else "Scheduled"
            loc = f" (📍 {ev['location']})" if ev.get("location") else ""
            lines.append(f"• *{time_part}* – {ev['title']}{loc}")
    else:
        lines.append("• _No meetings on your calendar today. Enjoy the focus time!_")
    lines.append("")

    # Medication section
    lines.append("💊 *Medications Today:*")
    if med_items:
        for m in med_items:
            icon = "✅" if m["status"] == "taken" else "⏳"
            inst = f" ({m['instructions']})" if m.get("instructions") else ""
            lines.append(f"• {icon} *{m['scheduled_time']}* – {m['med_name']} {m['dosage']}{inst}")
    else:
        lines.append("• _No active medications scheduled._")
    lines.append("")

    # Tasks section
    if pending_tasks:
        lines.append("✅ *Top Priorities for Today:*")
        for tk in pending_tasks:
            due = f" (⏳ Due: {tk['due_date']})" if tk.get("due_date") else ""
            lines.append(f"• {tk['task']}{due}")
        lines.append("")

    lines.append("💡 *Tip:* Type `/meds` anytime to check medication status or `/briefing` for an updated summary.")
    lines.append("Have a productive and healthy day! 🚀")

    return "\n".join(lines).strip()
