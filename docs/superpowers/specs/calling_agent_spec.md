# Spec: Autonomous Calling Agent (Twilio + Simulator)

## 1. Overview
The Calling Agent enables `@Taskzod_bot` to execute autonomous outbound phone calls on behalf of Mohammad Zohaib to accomplish real-world tasks (e.g., checking appointment availability with a clinic, verifying table reservations, inquiring about services).

It strictly follows the repository's standard "house style":
- **Entry**: Telegram `/call <phone> <mission>` or text intent (`call +91...`) via `app/telegram/handler.py` (thin dispatcher).
- **Core Domain**: `app/calls/` containing `__init__.py`, `schema.py`, `agent.py`, `tools.py`, `telephony.py`.
- **FastAPI Endpoints**: Thin routes in `app/fast_api_app.py` (`/calls/dispatch`, `/calls/twiml`, `/calls/respond`, `/calls/status`, `/calls/history`, `/calls/session/{id}`).
- **Conversation Brain**: Gemini 2.5 Flash via `step_call()` returning structured JSON (`{ spoken_text, is_complete, extracted_data }`) with offline heuristic fallback for test isolation.
- **Dual Transport**: Live Twilio PSTN (`<Say>` + `<Gather>`) if credentials are configured; in-process simulated dialogue if credentials are absent. Both use the exact same `step_call()` engine.
- **State & Memory**: GCS-backed session storage (`gs://inbox-triage-vault-507920/calls/{session_id}.json` + `/tmp/calls/` instance cache) with index at `calls/index.json`.
- **Workspace Integration**: Reuses `app.voice.tools.schedule_calendar_event()` inside `complete_call()`. Apps Script pulls `/calls/history` via `syncCallsToSheet()` into Google Drive sheet `My AI Phone Calls & Outreach Log`.

---

## 2. Locked Architectural Rules & Non-Negotiables

### 2.1 Form-Encoded Webhooks & TwiML Helpers
- Twilio webhooks (`/calls/twiml`, `/calls/respond`, `/calls/status`) post `application/x-www-form-urlencoded`, NOT JSON.
- Handlers parse form parameters: `SpeechResult`, `CallSid`, `CallStatus`, `RecordingUrl`, etc.
- TwiML generation is encapsulated into standalone functions in `app/calls/telephony.py` (`build_gather_twiml`, `build_hangup_twiml`) so they can be unit-tested directly without booting the FastAPI/ADK test server.

### 2.2 Session ID Propagation & Dual-Key Indexing
- Twilio `<Gather>` action MUST explicitly preserve `session_id`:
  `<Gather action="/calls/respond?session_id={session_id}" language="en-IN" speechTimeout="auto" timeout="5" actionOnEmptyResult="true">`
- When `calls.create()` is invoked, `call_sid` is persisted immediately to `CallSession` and in-memory index `call_sid -> session_id` before the recipient phone rings.
- `/calls/respond` and `/calls/status` resolve session via `session_id` query param, falling back to `CallSid` from form body.

### 2.3 Zero-Model Pickup (`/calls/twiml`)
- Opening greeting is precomputed at dispatch time via `step_call(session, "")` and stored in `session.transcript[0].text`.
- `/calls/twiml` strictly reads `session.transcript[0].text` into `<Say voice="Google.en-IN-Wavenet-A">`.
- `/calls/twiml` NEVER calls Gemini on pickup, eliminating cold-start delay and transcript duplication.

### 2.4 Strict Idempotency in `complete_call()`
- `complete_call(session)` is strictly idempotent: `if session.summary: return`.
- **Live Calls**: completed strictly from `/calls/status` upon terminal callback (`completed`, `failed`, `busy`, `no_answer`).
- **Simulated Calls**: completed strictly at the end of `run_simulated_call()`.
- `/calls/respond` NEVER calls `complete_call()`; it only returns hangup TwiML (`build_hangup_twiml()`).

### 2.5 Synchronous Cloud Run Execution for Simulator
- To prevent Cloud Run CPU throttling on background threads after HTTP response returns, `initiate_outbound_call()` in simulation mode runs `run_simulated_call()` synchronously.
- Capped at maximum 8 turns with brief spoken outputs (~60-80 tokens) to complete comfortably within Telegram's ~60s webhook timeout.
- In tests, the simulated recipient uses deterministic heuristic rules (confirming 5:30 PM slot); in live development without Twilio, it can use Gemini.

### 2.6 Environment & Base URL
- Telephony requires `PUBLIC_BASE_URL` (defaults to `https://inbox-triage-agent-723976801056.us-central1.run.app`).
- Twilio webhooks are configured with `{PUBLIC_BASE_URL}/calls/twiml?session_id={id}` and status callback `{PUBLIC_BASE_URL}/calls/status`.

### 2.7 Security & Dialing Protection
- Telegram invokes `initiate_outbound_call()` in-process.
- `POST /calls/dispatch` requires header `X-Calls-Token == CALLS_DISPATCH_TOKEN` (bypassed only when unset and `_is_testing()`).
- Twilio webhooks validate `X-Twilio-Signature` when credentials exist (bypassed in pytest).

### 2.8 E.164 & Audio Recording
- Dials with `record=True` so `RecordingUrl` is captured on status callbacks.
- Language is locked to `en-IN` (Indian English) with neural voice `Google.en-IN-Wavenet-A`.

---

## 3. Component Contracts

### 3.1 Schema (`app/calls/schema.py`)
- `CallStatus`: `initiated` | `ringing` | `in_progress` | `completed` | `failed` | `busy` | `no_answer`
- `CallTurn`: `speaker` (`ai` | `human`), `text`: str, `timestamp`: str
- `CallExtractedData`: 
  - `title`: Optional[str] = None
  - `start_time`: Optional[str] = None (ISO 8601, e.g. `2026-09-12T17:00:00`)
  - `end_time`: Optional[str] = None
  - `location`: Optional[str] = None
  - `description`: Optional[str] = None
  - `outcome`: str = "in_progress"
  - `fee`: Optional[str] = None
  - `requirements`: Optional[str] = None
  - `callback_needed`: bool = False
- `CallSession`:
  - `session_id`: str (UUID)
  - `chat_id`: Optional[int] = None
  - `to_number`: str (E.164)
  - `mission`: str
  - `status`: CallStatus = CallStatus.initiated
  - `call_sid`: Optional[str] = None
  - `created_at`: str
  - `duration_seconds`: int = 0
  - `transcript`: list[CallTurn] = []
  - `summary`: Optional[str] = None
  - `extracted_data`: Optional[CallExtractedData] = None
  - `recording_url`: Optional[str] = None
  - `mode`: str = "live"  # "live" | "simulated"
- `CallTurnResult`:
  - `spoken_text`: str
  - `is_complete`: bool
  - `extracted_data`: Optional[CallExtractedData] = None
- `CallDispatchResult`:
  - `status`: str
  - `session_id`: str
  - `call_sid`: Optional[str] = None
  - `mode`: str
  - `message`: str

### 3.2 Agent (`app/calls/agent.py`)
- `step_call(session: CallSession, human_text: str) -> CallTurnResult`:
  - System prompt: Mohammad Zohaib's personal executive assistant.
  - Generates 1 concise spoken sentence (max 60-80 tokens).
  - Handles clarifications, holds ("let me check"), negative responses ("no slots available").
  - Closes politely once mission objective is satisfied.
  - When `human_text == ""`: returns pre-computed opening greeting.
- `summarize_call(session: CallSession) -> dict`:
  - Generates executive call outcome, extracted structured facts, and formatted Telegram message.
- `_fallback_step_call(session, human_text)` & `_fallback_summarize_call(session)`:
  - Deterministic heuristic dialog fallback ensuring 100% offline pytest execution without API keys.

### 3.3 Session Store (`app/calls/tools.py`)
- `save_call_session(session: CallSession) -> None`:
  - Writes to `/tmp/calls/{session_id}.json`.
  - Maps `call_sid -> session_id` index.
  - Unless `_is_testing()`, syncs to `gs://inbox-triage-vault-507920/calls/{session_id}.json` and updates `calls/index.json`.
- `load_call_session(session_id_or_sid: str) -> Optional[CallSession]`:
  - Resolves `call_sid` to `session_id` if needed.
  - Checks in-memory cache, then `/tmp/calls/`, then GCS.
- `list_call_sessions() -> list[CallSession]`:
  - Loads index from GCS / local storage for `/calls/history`.
- `clear_call_records()`:
  - Resets session memory and test directory during pytest.

### 3.4 Telephony & Simulation (`app/calls/telephony.py`)
- TwiML Builders:
  - `build_gather_twiml(say_text: str, session_id: str) -> str`
  - `build_hangup_twiml(say_text: Optional[str] = None) -> str`
  - `build_empty_retry_twiml(session_id: str) -> str`
- `initiate_outbound_call(to_number: str, mission: str, chat_id: Optional[int] = None) -> CallDispatchResult`:
  1. Validates E.164 phone format.
  2. Creates `CallSession` in `initiated` status.
  3. Precomputes greeting via `step_call(session, "")` and appends as first `CallTurn` in transcript.
  4. If `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, and `TWILIO_PHONE_NUMBER` are configured:
     - Dials via `twilio.rest.Client.calls.create(url=f"{BASE_URL}/calls/twiml?session_id=...", status_callback=..., record=True)`.
     - Persists `call_sid` to session and maps `call_sid -> session_id`.
     - Returns `mode="live"`.
  5. Else:
     - Sets `mode="simulated"`.
     - Runs `run_simulated_call(session)` synchronously.
     - Returns `mode="simulated"`.
- `run_simulated_call(session: CallSession) -> None`:
  - Loops up to 8 turns: recipient provides answer, `step_call` steps dialog until complete.
  - Calls `complete_call(session)`.
- `complete_call(session: CallSession) -> None`:
  1. Idempotency check: if `session.summary` is already set, returns early.
  2. Calls `summarize_call(session)`.
  3. If `session.extracted_data` contains `start_time`, calls `app.voice.tools.schedule_calendar_event(...)`.
  4. If `session.chat_id`: pushes Telegram debrief card with outcome, transcript snippet, and 1-tap Calendar link (`generate_google_calendar_url`).
  5. Persists final session state to GCS.

### 3.5 API Endpoints (`app/fast_api_app.py`)
- `POST /calls/dispatch`:
  - Validates `X-Calls-Token`. Body: `{ to_number, mission, chat_id }`. Calls `initiate_outbound_call()`.
- `POST /calls/twiml`:
  - Form parsing. Resolves `session_id`. Reads `transcript[0].text`. Returns `build_gather_twiml(...)`.
- `POST /calls/respond`:
  - Form parsing (`SpeechResult`, `CallSid`). Resolves session. Calls `step_call(session, speech)`.
  - If complete: returns `build_hangup_twiml(result.spoken_text)`.
  - Else: returns `build_gather_twiml(result.spoken_text, session_id)`.
  - NEVER calls `complete_call()`.
- `POST /calls/status`:
  - Form parsing (`CallStatus`, `CallDuration`, `RecordingUrl`).
  - Maps status to `CallStatus`.
  - On terminal status (`completed`, `failed`, `busy`, `no-answer`): calls `complete_call(session)`.
- `GET /calls/history`: Returns call history index for Apps Script.
- `GET /calls/session/{session_id}`: Returns full transcript and session detail.

### 3.6 Telegram Handler (`app/telegram/handler.py`)
- Command `/call <phone> <mission>`
- Text intent: message starting with "call " followed by E.164 number.
- Calls `initiate_outbound_call(to_number, mission, chat_id)` in-process.
- Sends immediate dispatch card.

### 3.7 Google Apps Script (`integrations_gmail_code.js`)
- `syncCallsToSheet()`:
  - Fetches `GET /calls/history`.
  - Appends new calls to Google Sheet: **`My AI Phone Calls & Outreach Log`** with columns:
    `Call ID | Date | Recipient | Mission | Duration | Outcome | Extracted Details | Mode | Recording URL`.
  - Dedupes by `session_id`.
  - Hooked into `triageInbox()`.

---

## 4. Testing & Verification Isolation
- `tests/unit/test_calling_agent.py`:
  - Uses `app.voice.tools.clear_records()` and `app.calls.tools.clear_call_records()` in `setUp()` and `tearDown()` to prevent fixture leakage.
  - Tests TwiML builders directly as pure functions.
  - Tests `step_call()` and `summarize_call()` with heuristic fallbacks.
  - Tests `run_simulated_call()` end-to-end.
  - Tests `/calls/twiml`, `/calls/respond`, and `/calls/status` form-encoded handlers via FastAPI `TestClient`.
