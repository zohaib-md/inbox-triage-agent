import json
import logging
import os
import urllib.request
from typing import Any, Optional

from app.voice.agent import process_voice_or_text
from app.voice.schema import VoiceExtractionResult

logger = logging.getLogger("telegram_handler")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8793298330:AAEdVPw2fCtSrRaVEaxcHajHnEu1QNiwcmE")
TELEGRAM_API_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def send_telegram_message(chat_id: int | str, text: str, parse_mode: str = "Markdown") -> bool:
    """Sends a text message back to a Telegram chat."""
    url = f"{TELEGRAM_API_BASE}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        logger.error(f"Failed to send Telegram message: {e}")
        # Retry with plain text if markdown formatting failed
        if parse_mode == "Markdown":
            payload.pop("parse_mode", None)
            try:
                with urllib.request.urlopen(
                    urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}),
                    timeout=10,
                ) as resp:
                    return resp.status == 200
            except Exception:
                pass
        return False


def download_telegram_file(file_id: str) -> Optional[bytes]:
    """Downloads a file (e.g. voice note .ogg) from Telegram servers using file_id."""
    get_file_url = f"{TELEGRAM_API_BASE}/getFile?file_id={file_id}"
    try:
        with urllib.request.urlopen(get_file_url, timeout=10) as resp:
            res_data = json.loads(resp.read().decode("utf-8"))
            if not res_data.get("ok"):
                logger.error(f"getFile returned not ok: {res_data}")
                return None
            file_path = res_data["result"]["file_path"]

        download_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
        with urllib.request.urlopen(download_url, timeout=20) as resp:
            return resp.read()
    except Exception as e:
        logger.error(f"Error downloading file from Telegram: {e}")
        return None


def handle_telegram_update(update: dict[str, Any]) -> dict[str, Any]:
    """
    Main webhook dispatcher for Telegram updates.
    Handles /start, voice notes, audio files, and text messages.
    """
    message = update.get("message") or update.get("edited_message")
    if not message:
        return {"status": "ignored", "reason": "no_message"}

    chat_id = message["chat"]["id"]
    text = message.get("text", "")

    # Handle /start or /help commands
    if text.strip().startswith("/start") or text.strip().startswith("/help"):
        welcome_msg = (
            "👋 *Welcome to your Voice-to-Task Assistant!*\n\n"
            "Hold down the 🎙️ *microphone button* and speak a voice note (or type a message).\n\n"
            "For example:\n"
            "_\"Dentist appointment tomorrow at 4 PM, and remind me to pay electricity bill by Friday.\"_\n\n"
            "I will automatically schedule calendar events and organize your to-do list!"
        )
        send_telegram_message(chat_id, welcome_msg)
        return {"status": "ok", "action": "sent_welcome"}

    # Handle Voice Note or Audio
    voice = message.get("voice") or message.get("audio")
    if voice:
        file_id = voice["file_id"]
        mime_type = voice.get("mime_type", "audio/ogg")
        send_telegram_message(chat_id, "🎧 *Listening to your voice note...*")

        audio_bytes = download_telegram_file(file_id)
        if not audio_bytes:
            send_telegram_message(chat_id, "❌ *Sorry, could not download voice file from Telegram. Please try again!*")
            return {"status": "error", "reason": "download_failed"}

        result: VoiceExtractionResult = process_voice_or_text(
            audio_bytes=audio_bytes,
            mime_type=mime_type,
        )
    elif text:
        # Handle regular typed text
        result = process_voice_or_text(text=text)
    else:
        send_telegram_message(chat_id, "💡 Please send a voice note or text message.")
        return {"status": "ignored", "reason": "unsupported_message_type"}

    # Format output message
    reply_body = format_telegram_reply(result)
    send_telegram_message(chat_id, reply_body)

    return {
        "status": "ok",
        "events_count": len(result.events),
        "tasks_count": len(result.tasks),
    }


def format_telegram_reply(result: VoiceExtractionResult) -> str:
    """Formats the extracted events and tasks into a clean Telegram Markdown message."""
    lines = []

    if result.confirmation_message:
        lines.append(result.confirmation_message)
        lines.append("")

    if result.events:
        lines.append("📅 *Scheduled Calendar Events:*")
        for ev in result.events:
            loc = f" (📍 {ev.location})" if ev.location else ""
            lines.append(f"• *{ev.title}*\n  ⏰ `{ev.start_time}`{loc}")
        lines.append("")

    if result.tasks:
        lines.append("✅ *Actionable To-Do Items:*")
        for tk in result.tasks:
            due = f" (⏳ Due: {tk.due_date})" if tk.due_date else ""
            prio = "🔴 High" if tk.priority == "high" else "🟡 Medium" if tk.priority == "medium" else "🟢 Low"
            lines.append(f"• *{tk.task}*{due}\n  Priority: {prio} | Category: #{tk.category}")
        lines.append("")

    if not result.events and not result.tasks:
        lines.append("ℹ️ _No specific calendar events or tasks detected._")

    return "\n".join(lines).strip()


def set_telegram_webhook(webhook_url: str) -> dict[str, Any]:
    """Registers the webhook URL with Telegram."""
    url = f"{TELEGRAM_API_BASE}/setWebhook?url={webhook_url}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"ok": False, "error": str(e)}


def get_telegram_webhook_info() -> dict[str, Any]:
    """Fetches current webhook status from Telegram."""
    url = f"{TELEGRAM_API_BASE}/getWebhookInfo"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"ok": False, "error": str(e)}
