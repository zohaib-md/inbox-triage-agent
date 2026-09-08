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


# Main execution
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)


