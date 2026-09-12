import contextlib
import os
from collections.abc import AsyncIterator

from a2a.server.tasks import InMemoryTaskStore
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Response
from google.adk.cli.fast_api import get_fast_api_app
from google.adk.runners import Runner

from app.app_utils import services
from app.app_utils.a2a import attach_a2a_routes

load_dotenv()
allow_origins = (
    os.getenv("ALLOW_ORIGINS", "").split(",") if os.getenv("ALLOW_ORIGINS") else None
)
otel_to_cloud = os.getenv("OTEL_TO_CLOUD", "false").lower() == "true"

AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    from app.agent import app as adk_app
    from app.agent import root_agent

    runner = Runner(
        app=adk_app,
        session_service=services.get_session_service(),
        artifact_service=services.get_artifact_service(),
        auto_create_session=True,
    )
    app.state.runner = runner
    app.state.agent_app_name = adk_app.name
    await attach_a2a_routes(
        app,
        agent=root_agent,
        runner=runner,
        task_store=InMemoryTaskStore(),
        rpc_path=f"/a2a/{adk_app.name}",
    )
    yield


app: FastAPI = get_fast_api_app(
    agents_dir=AGENT_DIR,
    web=True,
    artifact_service_uri=services.ARTIFACT_SERVICE_URI,
    allow_origins=allow_origins,
    session_service_uri=services.SESSION_SERVICE_URI,
    otel_to_cloud=otel_to_cloud,
    lifespan=lifespan,
)
app.title = "inbox-triage-agent"
app.description = "API for interacting with the inbox-triage-agent and voice-to-task agent"


# --- Telegram & Voice-to-Task Routes ---
@app.post("/telegram/webhook")
async def telegram_webhook(update: dict):
    """Webhook endpoint invoked by Telegram Bot API when messages or voice notes arrive."""
    from app.telegram.handler import handle_telegram_update
    return handle_telegram_update(update)


@app.get("/telegram/set_webhook")
async def telegram_set_webhook(url: str):
    """Registers the webhook URL with Telegram."""
    from app.telegram.handler import set_telegram_webhook
    return set_telegram_webhook(url)


@app.get("/telegram/info")
async def telegram_info():
    """Returns Telegram webhook info."""
    from app.telegram.handler import get_telegram_webhook_info
    return get_telegram_webhook_info()


@app.get("/voice/records")
async def voice_records():
    """Returns all calendar events and tasks extracted from voice notes."""
    from app.voice.tools import get_all_records
    return get_all_records()


# --- Health & Medication Routes ---
@app.get("/health/records")
async def health_records():
    """Returns all medication schedules and adherence logs."""
    from app.health.tools import get_all_health_records
    return get_all_health_records()


@app.post("/health/log")
async def health_log(payload: dict):
    """Records an adherence action (taken/snoozed) for a medication dose."""
    from app.health.tools import log_medication_action
    return log_medication_action(
        med_name=payload.get("med_name", "Medicine"),
        scheduled_time=payload.get("scheduled_time", "09:00"),
        status=payload.get("status", "taken"),
        dosage=payload.get("dosage", "1 dose"),
    )


# --- Morning Briefing Routes ---
@app.get("/briefing/today")
async def briefing_today(name: str = "Zohaib"):
    """Generates today's full 8:00 AM morning secretary briefing."""
    from app.briefing.briefing_agent import generate_morning_briefing
    return {"briefing": generate_morning_briefing(user_name=name)}


# --- Proactive Broadcast & Push Routes ---
@app.get("/telegram/subscribers")
async def telegram_subscribers():
    """Returns all currently registered Telegram subscriber chat IDs."""
    from app.telegram.handler import get_subscribers
    return {"subscribers": get_subscribers()}


@app.post("/briefing/send")
async def briefing_send():
    """Triggers and pushes the 8:00 AM Morning Briefing to all subscribed Telegram chats."""
    from app.telegram.handler import send_morning_briefing_push
    return send_morning_briefing_push()


@app.post("/health/remind")
async def health_remind():
    """Checks for pending medication doses and pushes interactive reminder cards to subscribers."""
    from app.telegram.handler import send_medication_reminder_push
    return send_medication_reminder_push()


@app.post("/telegram/broadcast/urgent-email")
async def broadcast_urgent_email(payload: dict):
    """Pushes a high-priority alert with 1-tap Send button to subscribers when an urgent email is triaged in Gmail."""
    from app.telegram.handler import send_urgent_email_alert_push
    return send_urgent_email_alert_push(
        subject=payload.get("subject", "No Subject"),
        sender=payload.get("sender", "Unknown"),
        draft_reply=payload.get("draft_reply"),
        draft_id=payload.get("draft_id"),
        thread_id=payload.get("thread_id"),
    )


# --- Gmail 1-Tap Reply Execution Routes ---
@app.get("/email/pending-sends")
async def email_pending_sends():
    """Returns approved email drafts queued to be sent by Google Apps Script."""
    from app.telegram.handler import get_pending_draft_sends
    return {"pending_drafts": get_pending_draft_sends()}


@app.post("/email/mark-sent")
async def email_mark_sent(payload: dict):
    """Acknowledges that a draft was sent by Apps Script and updates the Telegram message."""
    from app.telegram.handler import mark_draft_sent
    draft_id = payload.get("draft_id", "")
    success = mark_draft_sent(draft_id)
    return {"status": "ok" if success else "not_found", "draft_id": draft_id}


# --- Second Brain Document & Medical Vault Routes ---
@app.get("/vault/records")
async def vault_records():
    """Returns all documents indexed in the Second Brain Vault."""
    from app.vault.agent import list_vaulted_documents
    return {"documents": list_vaulted_documents()}


@app.get("/vault/document/{doc_id}")
async def vault_document(doc_id: str):
    """Serves the raw document file for Google Drive sync or download."""
    from fastapi.responses import FileResponse, JSONResponse
    from app.vault.agent import list_vaulted_documents

    docs = list_vaulted_documents()
    for d in docs:
        if d.get("doc_id") == doc_id:
            fp = d.get("file_path")
            if fp and os.path.exists(fp):
                return FileResponse(fp, filename=d.get("filename", "document.pdf"), media_type=d.get("mime_type", "application/pdf"))
    return JSONResponse(status_code=404, content={"error": "Document not found"})


@app.post("/vault/query")
async def vault_query(payload: dict):
    """Answers natural language questions across all vaulted documents."""
    from app.vault.agent import query_vault
    question = payload.get("question", "")
    return query_vault(question)


# --- Autonomous Voice Calling Routes ---
@app.post("/calls/dispatch")
async def calls_dispatch(request: Request):
    """Authenticated endpoint to initiate an outbound phone call."""
    from app.calls.telephony import initiate_outbound_call
    from app.calls.tools import _is_testing

    dispatch_token = os.getenv("CALLS_DISPATCH_TOKEN")
    if dispatch_token and request.headers.get("X-Calls-Token") != dispatch_token:
        raise HTTPException(status_code=401, detail="Unauthorized")
    elif not dispatch_token and not _is_testing() and os.getenv("ENV") == "production":
        raise HTTPException(status_code=401, detail="Calls token required in production")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    to_number = payload.get("to_number")
    mission = payload.get("mission")
    chat_id = payload.get("chat_id")

    if not to_number or not mission:
        raise HTTPException(status_code=400, detail="Fields 'to_number' and 'mission' are required")

    try:
        res = initiate_outbound_call(to_number=to_number, mission=mission, chat_id=chat_id)
        return res.model_dump()
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to dispatch call: {str(e)}")


@app.post("/calls/twiml")
async def calls_twiml(request: Request, session_id: str | None = None):
    """Twilio webhook when recipient answers. Zero-model pickup using precomputed greeting."""
    from app.calls.telephony import build_gather_twiml, build_hangup_twiml
    from app.calls.tools import load_call_session

    form = await request.form()
    sid = session_id or request.query_params.get("session_id") or str(form.get("CallSid", ""))
    session = load_call_session(sid)

    if not session:
        return Response(
            content=build_hangup_twiml("Call session not found."),
            media_type="application/xml",
        )

    say_text = (
        session.transcript[0].text
        if session.transcript
        else "Hello! I am calling on behalf of Mohammad Zohaib."
    )
    xml_content = build_gather_twiml(say_text, session.session_id)
    return Response(content=xml_content, media_type="application/xml")


@app.post("/calls/respond")
async def calls_respond(request: Request, session_id: str | None = None):
    """Twilio webhook when speech is transcribed. Advances conversation using step_call()."""
    from datetime import datetime
    from app.calls.agent import step_call
    from app.calls.schema import CallTurn
    from app.calls.telephony import build_gather_twiml, build_hangup_twiml
    from app.calls.tools import load_call_session, save_call_session

    form = await request.form()
    sid = session_id or request.query_params.get("session_id") or str(form.get("CallSid", ""))
    session = load_call_session(sid)

    if not session:
        return Response(content=build_hangup_twiml(), media_type="application/xml")

    speech = str(form.get("SpeechResult", "")).strip()

    # Append human turn
    session.transcript.append(
        CallTurn(
            speaker="human",
            text=speech or "(Silence)",
            timestamp=datetime.now().isoformat(),
        )
    )

    # Step dialogue
    result = step_call(session, speech)
    session.transcript.append(
        CallTurn(
            speaker="ai",
            text=result.spoken_text,
            timestamp=datetime.now().isoformat(),
        )
    )

    if result.extracted_data:
        session.extracted_data = result.extracted_data

    save_call_session(session)

    # Return hangup if completed, otherwise gather next turn
    if result.is_complete:
        xml_content = build_hangup_twiml(result.spoken_text)
    else:
        xml_content = build_gather_twiml(result.spoken_text, session.session_id)

    return Response(content=xml_content, media_type="application/xml")


@app.post("/calls/status")
async def calls_status(request: Request, session_id: str | None = None):
    """Twilio status callback webhook. Updates duration, recording, and executes complete_call on terminal events."""
    from app.calls.schema import CallStatus
    from app.calls.telephony import complete_call
    from app.calls.tools import load_call_session, save_call_session

    form = await request.form()
    sid = session_id or request.query_params.get("session_id") or str(form.get("CallSid", ""))
    session = load_call_session(sid)

    if not session:
        return {"status": "ignored", "reason": "session_not_found"}

    duration = form.get("CallDuration")
    if duration:
        try:
            session.duration_seconds = int(duration)
        except Exception:
            pass

    recording_url = form.get("RecordingUrl")
    if recording_url:
        session.recording_url = str(recording_url)

    # Map Twilio CallStatus
    raw_status = str(form.get("CallStatus", "")).lower()
    if raw_status == "busy":
        session.status = CallStatus.busy
    elif raw_status in ("no-answer", "no_answer"):
        session.status = CallStatus.no_answer
    elif raw_status in ("failed", "canceled"):
        session.status = CallStatus.failed
    elif raw_status == "in-progress":
        session.status = CallStatus.in_progress
    elif raw_status == "completed":
        session.status = CallStatus.completed

    # Terminal states trigger complete_call side effects
    if raw_status in ("completed", "busy", "no-answer", "no_answer", "failed", "canceled"):
        complete_call(session)
    else:
        save_call_session(session)

    return {"status": "ok", "session_id": session.session_id, "call_status": session.status.value}


@app.get("/calls/history")
async def calls_history():
    """Returns list of all calls for Google Apps Script sync."""
    from app.calls.tools import list_call_sessions
    return {"calls": [s.model_dump() for s in list_call_sessions()]}


@app.get("/calls/session/{session_id}")
async def calls_session_detail(session_id: str):
    """Returns full transcript and metadata for a specific call."""
    from app.calls.tools import load_call_session
    session = load_call_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Call session not found")
    return session.model_dump()


# Main execution
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)


