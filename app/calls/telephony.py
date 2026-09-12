import logging
import os
import re
import uuid
from datetime import datetime
from typing import Optional

from twilio.twiml.voice_response import Gather, VoiceResponse

from app.calls.agent import step_call, summarize_call
from app.calls.schema import (
    CallDispatchResult,
    CallExtractedData,
    CallSession,
    CallStatus,
    CallTurn,
)
from app.calls.tools import _is_testing, load_call_session, save_call_session

logger = logging.getLogger("calls_telephony")

PUBLIC_BASE_URL = os.getenv(
    "PUBLIC_BASE_URL", "https://inbox-triage-agent-723976801056.us-central1.run.app"
).rstrip("/")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")

VOICE_NAME = "Google.en-IN-Wavenet-A"
VOICE_LANGUAGE = "en-IN"


def normalize_e164(phone: str) -> str:
    """Normalizes phone string to E.164 standard (+[country][number])."""
    cleaned = re.sub(r"[\s\-\(\)]", "", phone.strip())
    if not cleaned.startswith("+"):
        cleaned = "+" + cleaned
    if not re.match(r"^\+[1-9]\d{7,14}$", cleaned):
        raise ValueError(f"Invalid E.164 phone number: {phone}")
    return cleaned


# ==========================================
# Standalone Pure TwiML Builders
# ==========================================


def build_gather_twiml(say_text: str, session_id: str) -> str:
    """
    Builds TwiML response containing a Gather element for spoken input.
    Preserves session_id in the action query parameter.
    """
    response = VoiceResponse()
    gather = Gather(
        action=f"/calls/respond?session_id={session_id}",
        method="POST",
        input="speech",
        language=VOICE_LANGUAGE,
        speech_timeout="auto",
        timeout=5,
        action_on_empty_result=True,
    )
    gather.say(say_text, voice=VOICE_NAME, language=VOICE_LANGUAGE)
    response.append(gather)
    # Redirect if no speech was detected
    response.redirect(f"/calls/respond?session_id={session_id}")
    return str(response)


def build_hangup_twiml(say_text: Optional[str] = None) -> str:
    """Builds TwiML that speaks a closing statement (if provided) and hangs up."""
    response = VoiceResponse()
    if say_text:
        response.say(say_text, voice=VOICE_NAME, language=VOICE_LANGUAGE)
    response.hangup()
    return str(response)


def build_empty_retry_twiml(session_id: str) -> str:
    """Builds retry TwiML when no speech was detected."""
    response = VoiceResponse()
    gather = Gather(
        action=f"/calls/respond?session_id={session_id}",
        method="POST",
        input="speech",
        language=VOICE_LANGUAGE,
        speech_timeout="auto",
        timeout=5,
        action_on_empty_result=True,
    )
    gather.say(
        "I didn't quite catch that. Could you please repeat?",
        voice=VOICE_NAME,
        language=VOICE_LANGUAGE,
    )
    response.append(gather)
    response.hangup()
    return str(response)


# ==========================================
# Dispatch & Orchestration
# ==========================================


def initiate_outbound_call(
    to_number: str, mission: str, chat_id: Optional[int] = None
) -> CallDispatchResult:
    """
    Initiates an outbound phone call.
    Validates E.164, initializes session, precomputes zero-model opening greeting.
    Dials via Twilio PSTN if credentials are configured; otherwise runs synchronous simulator.
    """
    normalized_phone = normalize_e164(to_number)
    session_id = str(uuid.uuid4())

    session = CallSession(
        session_id=session_id,
        chat_id=chat_id,
        to_number=normalized_phone,
        mission=mission,
        status=CallStatus.initiated,
        created_at=datetime.now().isoformat(),
    )

    # 1. Zero-model opening greeting precomputed at dispatch
    greeting_result = step_call(session, "")
    session.transcript.append(
        CallTurn(
            speaker="ai",
            text=greeting_result.spoken_text,
            timestamp=datetime.now().isoformat(),
        )
    )

    # 2. Live Twilio vs Simulator
    has_twilio = bool(
        TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_PHONE_NUMBER
    )

    if has_twilio and not _is_testing():
        try:
            from twilio.rest import Client

            session.mode = "live"
            client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
            twiml_url = f"{PUBLIC_BASE_URL}/calls/twiml?session_id={session_id}"
            status_url = f"{PUBLIC_BASE_URL}/calls/status?session_id={session_id}"

            call = client.calls.create(
                to=normalized_phone,
                from_=TWILIO_PHONE_NUMBER,
                url=twiml_url,
                status_callback=status_url,
                status_callback_event=["initiated", "ringing", "answered", "completed"],
                status_callback_method="POST",
                record=True,
            )
            session.call_sid = call.sid
            save_call_session(session)

            return CallDispatchResult(
                status="success",
                session_id=session_id,
                call_sid=call.sid,
                mode="live",
                message=f"Live outbound call initiated to {normalized_phone} via Twilio.",
            )
        except Exception as e:
            logger.error(f"Failed to initiate Twilio call: {e}")
            session.status = CallStatus.failed
            save_call_session(session)
            return CallDispatchResult(
                status="error",
                session_id=session_id,
                call_sid=None,
                mode="live",
                message=f"Twilio initiation failed: {str(e)}",
            )
    else:
        # Simulator Mode (Synchronous execution for Cloud Run safety)
        session.mode = "simulated"
        save_call_session(session)
        run_simulated_call(session)
        return CallDispatchResult(
            status="success",
            session_id=session_id,
            call_sid=None,
            mode="simulated",
            message=f"Simulated phone call executed successfully for {normalized_phone}.",
        )


def run_simulated_call(session: CallSession) -> CallSession:
    """
    Executes a synchronous simulated phone call up to 8 turns.
    Guarantees execution completes within Telegram's timeout without background CPU throttling.
    """
    session.status = CallStatus.in_progress

    # Deterministic simulated script for testing / offline execution
    script_turns = [
        "Hello! Dr. Verma's clinic here. How can I help you?",
        "Yes, we have an opening available today at 5:30 PM. Would you like me to book it for Mohammad Zohaib?",
        "Great, the appointment for 5:30 PM is confirmed. See you then!",
    ]

    for turn_idx, human_text in enumerate(script_turns):
        # 1. Human turn
        session.transcript.append(
            CallTurn(
                speaker="human",
                text=human_text,
                timestamp=datetime.now().isoformat(),
            )
        )

        # 2. Agent step
        result = step_call(session, human_text)
        session.transcript.append(
            CallTurn(
                speaker="ai",
                text=result.spoken_text,
                timestamp=datetime.now().isoformat(),
            )
        )

        if result.extracted_data:
            session.extracted_data = result.extracted_data

        if result.is_complete or turn_idx >= 7:
            break

    session.duration_seconds = len(session.transcript) * 12
    return complete_call(session)


def complete_call(session: CallSession) -> CallSession:
    """
    Idempotent post-call side-effects pipeline:
    1. Checks if session is already summarized (idempotent early return).
    2. Does not overwrite failed/busy/no_answer with completed.
    3. Runs summarize_call().
    4. Auto-schedules calendar event in app.voice.tools if start_time was extracted.
    5. Sends Telegram debrief card with 1-tap Google Calendar link.
    6. Persists session state to GCS and local cache.
    """
    # 1. Idempotency guard
    if session.summary:
        return session

    # 2. Do not force completed on failures
    if session.status not in (
        CallStatus.failed,
        CallStatus.busy,
        CallStatus.no_answer,
    ):
        session.status = CallStatus.completed

    # 3. Summarize call
    debrief = summarize_call(session)
    session.summary = debrief.get("summary", "Call concluded.")
    if debrief.get("extracted_data"):
        session.extracted_data = debrief["extracted_data"]

    # 4. Seamless Google Calendar integration via app.voice.tools
    if session.extracted_data and session.extracted_data.start_time:
        try:
            from app.voice.tools import schedule_calendar_event

            schedule_calendar_event(
                title=session.extracted_data.title or f"Appointment: {session.mission}",
                start_time=session.extracted_data.start_time,
                end_time=session.extracted_data.end_time,
                location=session.extracted_data.location,
                description=(
                    session.extracted_data.description
                    or f"Scheduled via AI Call to {session.to_number}. Mission: {session.mission}"
                ),
            )
        except Exception as e:
            logger.error(f"Failed to auto-schedule calendar event: {e}")

    # 5. Telegram debrief card
    if session.chat_id:
        try:
            from app.telegram.handler import send_telegram_message

            tg_text = debrief.get("telegram_message") or session.summary
            send_telegram_message(chat_id=session.chat_id, text=tg_text)
        except Exception as e:
            logger.error(f"Failed to send Telegram debrief card: {e}")

    # 6. Final save
    save_call_session(session)
    return session
