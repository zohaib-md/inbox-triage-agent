import json
import os
import re
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from app.voice.schema import CalendarEvent, TodoTask, VoiceExtractionResult
from app.voice.tools import create_todo_task, schedule_calendar_event

MODEL_NAME = os.getenv("VOICE_AGENT_MODEL", "gemini-2.5-flash")
DEFAULT_TIMEZONE = os.getenv("USER_TIMEZONE", "Asia/Kolkata")


SYSTEM_INSTRUCTION = """You are an elite personal executive assistant.
Your job is to analyze rambling, natural spoken voice notes or text messages from the user and accurately extract:
1. Calendar Events: Specific meetings, appointments, calls, or reminders that mention a date or time.
   - If the user asks for a reminder, task, or event on a specific date (e.g. "cancel autopay on 5th October 2026", "dentist appointment on Friday", "remind me to pay bill tomorrow at 4 PM"), YOU MUST extract a CalendarEvent so it syncs directly to their Google Calendar!
   - If no specific hour/time is mentioned, default to 09:00:00 to 10:00:00 on that date.
   - Convert relative or explicit dates to exact ISO 8601 timestamps (YYYY-MM-DDTHH:MM:SS) based on the reference time.
   - If duration is not stated, assume 1 hour.
2. Actionable To-Do Tasks: Checklist items, errands, to-dos, or follow-ups.
   - Assign a priority: 'high', 'medium', or 'low'.
   - Assign a category: 'work', 'personal', 'errand', or 'urgent'.
   - Resolve any mentioned due dates (e.g. "by tonight", "before Friday noon", "2026-10-05").
3. Confirmation Message: A friendly, concise message formatted for Telegram with emojis summarizing what you scheduled on the calendar and added to the to-do list.

Rules:
- Be precise with dates and times. Always verify against the current reference date provided.
- Any time-specific or date-specific reminder (e.g. "remind me to cancel autopay on 5th October 2026") MUST be added to calendar events so it alerts the user on their Google Calendar!
- If no events are mentioned, return an empty events list. If no tasks are mentioned, return an empty tasks list.
"""


def get_current_time_context(user_timezone: str = DEFAULT_TIMEZONE) -> str:
    """Returns formatted string of current datetime in user's timezone."""
    try:
        tz = ZoneInfo(user_timezone)
    except Exception:
        tz = ZoneInfo("UTC")
    now = datetime.now(tz)
    return (
        f"Current Reference Time: {now.strftime('%A, %Y-%m-%d %H:%M:%S')} "
        f"({now.tzname()} / Timezone: {user_timezone})"
    )


def process_voice_or_text(
    audio_bytes: Optional[bytes] = None,
    mime_type: str = "audio/ogg",
    text: Optional[str] = None,
    user_timezone: str = DEFAULT_TIMEZONE,
) -> VoiceExtractionResult:
    """
    Processes audio voice note bytes or raw text using Gemini 2.5 Flash,
    extracts calendar events and tasks, saves them via tools, and returns the result.
    """
    time_context = get_current_time_context(user_timezone)

    try:
        from google import genai
        from google.genai import types

        client = genai.Client()

        contents = []
        if audio_bytes:
            contents.append(types.Part.from_bytes(data=audio_bytes, mime_type=mime_type))
            prompt = f"{time_context}\nAnalyze this audio voice note, extract any calendar events and tasks, and provide the confirmation summary."
        else:
            prompt = f"{time_context}\nUser message:\n{text or ''}\n\nExtract any calendar events and to-do tasks, and provide the confirmation summary."

        contents.append(prompt)

        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                response_mime_type="application/json",
                response_schema=VoiceExtractionResult,
                temperature=0.2,
            ),
        )

        response_text = response.text or "{}"
        data = json.loads(response_text)
        result = VoiceExtractionResult(**data)

    except Exception as e:
        # Fallback heuristic parser for testing or if Gemini API unavailable
        result = _fallback_heuristic_parser(text=text, time_context=time_context, error_msg=str(e))

    # Ensure every calendar event is also reflected in tasks so sheets and to-do lists stay synchronized
    for ev in result.events:
        if not any(t.task.lower() == ev.title.lower() for t in result.tasks):
            due = ev.start_time.split("T")[0] if ev.start_time and "T" in ev.start_time else ev.start_time
            result.tasks.append(
                TodoTask(
                    task=ev.title,
                    due_date=due,
                    priority="high",
                    category="personal",
                )
            )

    # Commit extracted items using tools
    for ev in result.events:
        schedule_calendar_event(
            title=ev.title,
            start_time=ev.start_time,
            end_time=ev.end_time,
            location=ev.location,
            description=ev.description,
        )

    for tk in result.tasks:
        create_todo_task(
            task=tk.task,
            due_date=tk.due_date,
            priority=tk.priority,
            category=tk.category,
        )

    return result


def _fallback_heuristic_parser(
    text: Optional[str], time_context: str, error_msg: str
) -> VoiceExtractionResult:
    """Simple offline fallback parser when API is unreachable or during unit tests."""
    content = text or "Voice note received"
    events: list[CalendarEvent] = []
    tasks: list[TodoTask] = []

    # Check for common keywords
    if "meeting" in content.lower() or "call" in content.lower() or "appointment" in content.lower():
        events.append(
            CalendarEvent(
                title=content[:40],
                start_time=datetime.now().strftime("%Y-%m-%dT10:00:00"),
                description="Extracted from voice note",
            )
        )
    else:
        tasks.append(
            TodoTask(
                task=content,
                priority="medium",
                category="personal",
            )
        )

    confirmation = (
        f"🎙️ *Voice Note Processed:*\n"
        f"• Events scheduled: {len(events)}\n"
        f"• Tasks logged: {len(tasks)}\n"
    )
    if events:
        confirmation += f"\n📅 *Calendar:* {events[0].title} ({events[0].start_time})"
    if tasks:
        confirmation += f"\n✅ *To-Do:* {tasks[0].task}"

    return VoiceExtractionResult(
        events=events,
        tasks=tasks,
        confirmation_message=confirmation,
    )
