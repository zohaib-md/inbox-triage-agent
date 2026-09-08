import json
import os
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from app.health.schema import MedicationExtractionResult, MedicationSchedule
from app.health.tools import add_medication_schedule

MODEL_NAME = os.getenv("HEALTH_AGENT_MODEL", "gemini-2.5-flash")
DEFAULT_TIMEZONE = os.getenv("USER_TIMEZONE", "Asia/Kolkata")

HEALTH_SYSTEM_INSTRUCTION = """You are an empathetic, precise personal healthcare assistant.
Your job is to analyze rambling or natural voice notes/messages from the user about their prescriptions, vitamins, or medications, and extract structured medication schedules.

For each medication mentioned, extract:
1. name: Exact name of the medication or supplement (e.g. 'Amoxicillin', 'Vitamin D3', 'Metformin').
2. dosage: Specific dosage if mentioned (e.g. '500mg', '1000 IU', '1 tablet', '2 drops'). Default to '1 dose' if unspecified.
3. times: Daily times in 24-hour HH:MM format.
   - If user says 'morning' or 'breakfast', use '09:00'.
   - If user says 'lunch' or 'afternoon', use '13:00'.
   - If user says 'dinner' or 'evening', use '20:00'.
   - If user says 'night' or 'bedtime', use '22:00'.
   - If user says 'twice a day', use ['09:00', '21:00'].
   - If user says 'three times a day', use ['08:00', '14:00', '20:00'].
4. instructions: Contextual notes (e.g. 'after food', 'with full glass of water', 'before breakfast').
5. duration_days: Number of days if a specific course was specified (e.g. 'for 7 days' -> 7, 'for a week' -> 7). Leave null for chronic/daily vitamins.
6. start_date: Current date provided.

Provide a warm, reassuring confirmation message formatted in Telegram Markdown with emojis.
"""


def process_medication_intake(
    audio_bytes: Optional[bytes] = None,
    mime_type: str = "audio/ogg",
    text: Optional[str] = None,
    user_timezone: str = DEFAULT_TIMEZONE,
) -> MedicationExtractionResult:
    """Extracts medication schedules from voice note or text using Gemini 2.5 Flash."""
    try:
        tz = ZoneInfo(user_timezone)
    except Exception:
        tz = ZoneInfo("UTC")
    today_str = datetime.now(tz).strftime("%Y-%m-%d")

    try:
        from google import genai
        from google.genai import types

        client = genai.Client()
        contents = []

        prompt_context = f"Today's Date: {today_str} (Timezone: {user_timezone})"
        if audio_bytes:
            contents.append(types.Part.from_bytes(data=audio_bytes, mime_type=mime_type))
            contents.append(f"{prompt_context}\nAnalyze this audio voice note and extract any medication schedules.")
        else:
            contents.append(f"{prompt_context}\nUser statement:\n{text or ''}\n\nExtract any medication schedules.")

        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=HEALTH_SYSTEM_INSTRUCTION,
                response_mime_type="application/json",
                response_schema=MedicationExtractionResult,
                temperature=0.2,
            ),
        )

        data = json.loads(response.text or "{}")
        result = MedicationExtractionResult(**data)

    except Exception as e:
        # Heuristic fallback parser
        result = _fallback_medication_parser(text=text, today_str=today_str, error_msg=str(e))

    # Commit extracted schedules
    for med in result.medications:
        add_medication_schedule(
            name=med.name,
            dosage=med.dosage,
            times=med.times,
            instructions=med.instructions,
            duration_days=med.duration_days,
            start_date=med.start_date or today_str,
        )

    return result


def _fallback_medication_parser(
    text: Optional[str], today_str: str, error_msg: str
) -> MedicationExtractionResult:
    """Offline heuristic fallback for medication extraction."""
    content = (text or "").strip()
    words = content.split()
    med_name = words[0].title() if words else "Medicine"

    # Default times based on common keywords
    times = ["09:00"]
    if "twice" in content.lower():
        times = ["09:00", "21:00"]
    elif "night" in content.lower() or "bed" in content.lower():
        times = ["22:00"]

    schedule = MedicationSchedule(
        name=med_name,
        dosage="1 dose",
        times=times,
        instructions="take as directed",
        start_date=today_str,
    )

    times_str = ", ".join(times)
    msg = (
        f"💊 *Medication Reminder Set!*\n\n"
        f"• *{med_name}*\n"
        f"  ⏰ Daily at: `{times_str}`\n"
        f"  ℹ️ Instructions: take as directed"
    )

    return MedicationExtractionResult(
        medications=[schedule],
        confirmation_message=msg,
    )
