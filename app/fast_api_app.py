import contextlib
import os
from collections.abc import AsyncIterator

from a2a.server.tasks import InMemoryTaskStore
from dotenv import load_dotenv
from fastapi import FastAPI
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


# Main execution
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)


