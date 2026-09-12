import json
import logging
import os
from typing import Optional
from app.calls.schema import CallSession

logger = logging.getLogger("calls_tools")

CALLS_DIR = os.getenv("CALLS_STORAGE_DIR", "/tmp/calls")
GCS_VAULT_BUCKET = os.getenv("GCS_VAULT_BUCKET", "inbox-triage-vault-507920")

os.makedirs(CALLS_DIR, exist_ok=True)

# In-memory session and lookup caches
CALL_SESSIONS: dict[str, CallSession] = {}
CALL_SID_TO_SESSION_ID: dict[str, str] = {}


def _is_testing() -> bool:
    return "PYTEST_CURRENT_TEST" in os.environ or os.getenv("TESTING") == "true"


def save_call_session(session: CallSession) -> None:
    """Saves session to memory, local /tmp cache, and GCS bucket."""
    CALL_SESSIONS[session.session_id] = session
    if session.call_sid:
        CALL_SID_TO_SESSION_ID[session.call_sid] = session.session_id

    local_file = os.path.join(CALLS_DIR, f"{session.session_id}.json")
    session_dict = session.model_dump()

    try:
        with open(local_file, "w") as f:
            json.dump(session_dict, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save local call session {session.session_id}: {e}")

    # GCS Persistence
    if GCS_VAULT_BUCKET and not _is_testing():
        try:
            from google.cloud import storage
            client = storage.Client()
            bucket = client.bucket(GCS_VAULT_BUCKET)
            blob = bucket.blob(f"calls/{session.session_id}.json")
            blob.upload_from_string(json.dumps(session_dict, indent=2), content_type="application/json")

            # Update index
            _update_gcs_index(client, bucket, session)
        except Exception as e:
            logger.warning(f"Could not persist call session to GCS: {e}")


def load_call_session(identifier: str) -> Optional[CallSession]:
    """Loads session by session_id or call_sid from memory, /tmp, or GCS."""
    if not identifier:
        return None

    # Resolve call_sid to session_id if known
    session_id = CALL_SID_TO_SESSION_ID.get(identifier, identifier)

    # 1. In-memory
    if session_id in CALL_SESSIONS:
        return CALL_SESSIONS[session_id]

    # 2. Local /tmp cache
    local_file = os.path.join(CALLS_DIR, f"{session_id}.json")
    if os.path.exists(local_file):
        try:
            with open(local_file, "r") as f:
                data = json.load(f)
                session = CallSession(**data)
                CALL_SESSIONS[session.session_id] = session
                if session.call_sid:
                    CALL_SID_TO_SESSION_ID[session.call_sid] = session.session_id
                return session
        except Exception as e:
            logger.error(f"Error loading session file {local_file}: {e}")

    # 3. Cloud Storage
    if GCS_VAULT_BUCKET and not _is_testing():
        try:
            from google.cloud import storage
            client = storage.Client()
            bucket = client.bucket(GCS_VAULT_BUCKET)
            blob = bucket.blob(f"calls/{session_id}.json")
            if blob.exists():
                data = json.loads(blob.download_as_text())
                session = CallSession(**data)
                CALL_SESSIONS[session.session_id] = session
                if session.call_sid:
                    CALL_SID_TO_SESSION_ID[session.call_sid] = session.session_id
                return session
        except Exception as e:
            logger.warning(f"Could not load call session from GCS: {e}")

    return None


def list_call_sessions() -> list[CallSession]:
    """Returns all call sessions ordered by most recent."""
    sessions: dict[str, CallSession] = dict(CALL_SESSIONS)

    # Read from local files
    if os.path.exists(CALLS_DIR):
        for fname in os.listdir(CALLS_DIR):
            if fname.endswith(".json") and fname != "index.json":
                sid = fname[:-5]
                if sid not in sessions:
                    sess = load_call_session(sid)
                    if sess:
                        sessions[sess.session_id] = sess

    # Read from GCS index if available
    if GCS_VAULT_BUCKET and not _is_testing():
        try:
            from google.cloud import storage
            client = storage.Client()
            bucket = client.bucket(GCS_VAULT_BUCKET)
            blob = bucket.blob("calls/index.json")
            if blob.exists():
                index_data = json.loads(blob.download_as_text())
                for item in index_data:
                    sid = item.get("session_id")
                    if sid and sid not in sessions:
                        sess = load_call_session(sid)
                        if sess:
                            sessions[sess.session_id] = sess
        except Exception as e:
            logger.warning(f"Could not load calls index from GCS: {e}")

    res = list(sessions.values())
    res.sort(key=lambda x: x.created_at, reverse=True)
    return res


def clear_call_records() -> None:
    """Clears all in-memory and local session records (for hermetic testing)."""
    CALL_SESSIONS.clear()
    CALL_SID_TO_SESSION_ID.clear()
    if os.path.exists(CALLS_DIR):
        for fname in os.listdir(CALLS_DIR):
            if fname.endswith(".json"):
                try:
                    os.remove(os.path.join(CALLS_DIR, fname))
                except Exception:
                    pass


def _update_gcs_index(client, bucket, session: CallSession) -> None:
    """Updates calls/index.json in GCS."""
    index_blob = bucket.blob("calls/index.json")
    index = []
    if index_blob.exists():
        try:
            index = json.loads(index_blob.download_as_text())
        except Exception:
            index = []

    # Update or append
    entry = {
        "session_id": session.session_id,
        "call_sid": session.call_sid,
        "to_number": session.to_number,
        "mission": session.mission,
        "status": session.status.value,
        "created_at": session.created_at,
        "duration_seconds": session.duration_seconds,
        "mode": session.mode,
    }
    index = [i for i in index if i.get("session_id") != session.session_id]
    index.insert(0, entry)
    index_blob.upload_from_string(json.dumps(index[:100], indent=2), content_type="application/json")
