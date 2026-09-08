import json
import logging
import os
import re
import urllib.request
from typing import Any, Optional

from app.briefing.briefing_agent import generate_morning_briefing
from app.health.agent import process_medication_intake
from app.health.tools import get_today_medication_status, log_medication_action
from app.transit.agent import track_flight_status, track_train_status
from app.voice.agent import process_voice_or_text
from app.voice.schema import VoiceExtractionResult


logger = logging.getLogger("telegram_handler")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8793298330:AAEdVPw2fCtSrRaVEaxcHajHnEu1QNiwcmE")
TELEGRAM_API_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def send_telegram_message(
    chat_id: int | str,
    text: str,
    reply_markup: Optional[dict[str, Any]] = None,
    parse_mode: str = "Markdown",
) -> bool:
    """Sends a text or interactive message back to a Telegram chat."""
    url = f"{TELEGRAM_API_BASE}/sendMessage"
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

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


def edit_telegram_message(
    chat_id: int | str,
    message_id: int,
    text: str,
    parse_mode: str = "Markdown",
) -> bool:
    """Edits an existing Telegram message (e.g. after tapping an inline button)."""
    url = f"{TELEGRAM_API_BASE}/editMessageText"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": parse_mode,
    }
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        logger.error(f"Error editing message: {e}")
        return False


def answer_callback_query(callback_query_id: str, text: str = "Logged! ✅") -> bool:
    """Sends a toast popup acknowledgment for a tapped button."""
    url = f"{TELEGRAM_API_BASE}/answerCallbackQuery"
    payload = {
        "callback_query_id": callback_query_id,
        "text": text,
        "show_alert": False,
    }
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except Exception:
        return False


def download_telegram_file(file_id: str) -> Optional[bytes]:
    """Downloads a voice file (.ogg) from Telegram servers using file_id."""
    get_file_url = f"{TELEGRAM_API_BASE}/getFile?file_id={file_id}"
    try:
        with urllib.request.urlopen(get_file_url, timeout=10) as resp:
            res_data = json.loads(resp.read().decode("utf-8"))
            if not res_data.get("ok"):
                return None
            file_path = res_data["result"]["file_path"]

        download_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
        with urllib.request.urlopen(download_url, timeout=20) as resp:
            return resp.read()
    except Exception as e:
        logger.error(f"Error downloading file from Telegram: {e}")
        return None


def generate_google_calendar_url(
    title: str,
    start_iso: str,
    end_iso: Optional[str] = None,
    details: Optional[str] = None,
    location: Optional[str] = None,
) -> str:
    """Generates a 1-click URL to save the event directly into Google Calendar."""
    import urllib.parse
    from datetime import datetime, timedelta

    try:
        st = datetime.fromisoformat(start_iso)
        et = datetime.fromisoformat(end_iso) if end_iso else st + timedelta(hours=1)
        fmt = "%Y%m%dT%H%M%S"
        dates = f"{st.strftime(fmt)}/{et.strftime(fmt)}"
    except Exception:
        dates = start_iso.replace("-", "").replace(":", "")

    params = {
        "action": "TEMPLATE",
        "text": title,
        "dates": dates,
    }
    if details:
        params["details"] = details
    if location:
        params["location"] = location
    return "https://calendar.google.com/calendar/render?" + urllib.parse.urlencode(params)


def handle_telegram_update(update: dict[str, Any]) -> dict[str, Any]:
    """
    Main webhook dispatcher for Telegram updates.
    Handles callback_queries (button taps), voice notes, and text messages.
    """
    # 1. Handle Interactive Inline Button Clicks (Callbacks)
    if "callback_query" in update:
        cq = update["callback_query"]
        cq_id = cq["id"]
        data = cq.get("data", "")
        chat_id = cq["message"]["chat"]["id"]
        msg_id = cq["message"]["message_id"]

        if data.startswith("take_med:"):
            # format: take_med:<med_name>:<time>
            parts = data.split(":")
            med_name = parts[1] if len(parts) > 1 else "Medication"
            sched_time = parts[2] if len(parts) > 2 else "Scheduled"

            log_medication_action(med_name=med_name, scheduled_time=sched_time, status="taken")
            answer_callback_query(cq_id, text=f"✅ Logged {med_name} as taken!")

            updated_text = f"✅ *Logged:* You took *{med_name}* (Scheduled: `{sched_time}`). Great job staying consistent!"
            edit_telegram_message(chat_id, msg_id, updated_text)
            return {"status": "ok", "action": "med_taken_logged"}

        elif data.startswith("snooze_med:"):
            parts = data.split(":")
            med_name = parts[1] if len(parts) > 1 else "Medication"
            sched_time = parts[2] if len(parts) > 2 else "Scheduled"

            log_medication_action(med_name=med_name, scheduled_time=sched_time, status="snoozed")
            answer_callback_query(cq_id, text="⏰ Snoozed for 15 minutes!")

            updated_text = f"⏰ *Snoozed:* {med_name} postponed. Remember to take it with water soon!"
            edit_telegram_message(chat_id, msg_id, updated_text)
            return {"status": "ok", "action": "med_snoozed"}

        elif data.startswith("refresh_transit:"):
            # format: refresh_transit:<mode>:<identifier>
            parts = data.split(":")
            mode = parts[1] if len(parts) > 1 else "flight"
            ident = parts[2] if len(parts) > 2 else ""

            answer_callback_query(cq_id, text=f"🔄 Refreshing live {mode} status...")

            if mode == "flight":
                res = track_flight_status(ident)
            else:
                res = track_train_status(ident)

            reply_markup = {
                "inline_keyboard": [
                    [{"text": "🔄 Refresh Live Status", "callback_data": res.get("refresh_callback", data)}]
                ]
            }
            edit_telegram_message(chat_id, msg_id, res["formatted_reply"])
            return {"status": "ok", "action": f"transit_refreshed_{mode}"}

        return {"status": "ignored"}

    # 2. Handle Regular Messages
    message = update.get("message") or update.get("edited_message")
    if not message:
        return {"status": "ignored", "reason": "no_message"}

    chat_id = message["chat"]["id"]
    text = (message.get("text") or "").strip()

    # Commands: /start, /help
    if text.startswith("/start") or text.startswith("/help"):
        welcome_msg = (
            "👋 *Welcome to your Personal AI Assistant!*\n\n"
            "Here is everything you can do:\n\n"
            "✈️ *Real-Time Flights, Trains & PNR*\n"
            "• `/flight <number>` e.g. `/flight 6E 204` or `/flight AI 432`\n"
            "• `/train <number/name>` e.g. `/train 12004` or `/train Vande Bharat`\n"
            "• `/pnr <10-digit-pnr>` e.g. `/pnr 2839182910`\n"
            "• Tap `[ 🔄 Refresh Status ]` anytime before boarding!\n\n"
            "🔍 *Live Web Search & Local Scout*\n"
            "Ask anything: _\"Top cafes in Hazratganj, Lucknow\"_ or type `/search <topic>`\n\n"
            "🎙️ *Voice-to-Task & Calendar*\n"
            "Speak naturally: _\"Doctor appointment tomorrow at 4 PM, and remind me to pay electricity bill tonight.\"_\n\n"
            "💊 *Medicine Reminders*\n"
            "Speak or type: _\"Remind me to take Vitamin D3 1000 IU every morning at 9 AM.\"_\n"
            "• Type `/meds` to see today's pills and adherence status.\n\n"
            "☀️ *Daily Morning Secretary*\n"
            "• Type `/briefing` for your complete morning briefing (Weather + Calendar + Meds + Tasks)!\n\n"
            "How can I help you today?"
        )
        send_telegram_message(chat_id, welcome_msg)
        return {"status": "ok", "action": "sent_welcome"}

    # Command: /flight <flight_number>
    if text.startswith("/flight"):
        query = text[7:].strip()
        if not query:
            send_telegram_message(
                chat_id,
                "✈️ *Please provide a flight number, for example:*\n"
                "`/flight 6E 204`\n"
                "`/flight AI 432`"
            )
            return {"status": "ok", "action": "sent_flight_help"}
        flight_res = track_flight_status(query)
        reply_markup = {
            "inline_keyboard": [
                [{"text": "🔄 Refresh Live Status", "callback_data": flight_res["refresh_callback"]}]
            ]
        }
        send_telegram_message(chat_id, flight_res["formatted_reply"], reply_markup=reply_markup)
        return {"status": "ok", "action": "flight_tracked"}

    # Command: /train <train_number_or_name>
    if text.startswith("/train"):
        query = text[6:].strip()
        if not query:
            send_telegram_message(
                chat_id,
                "🚆 *Please provide a train number or name, for example:*\n"
                "`/train 12004`\n"
                "`/train 22436 Vande Bharat`"
            )
            return {"status": "ok", "action": "sent_train_help"}
        train_res = track_train_status(query)
        reply_markup = {
            "inline_keyboard": [
                [{"text": "🔄 Refresh Live Status", "callback_data": train_res["refresh_callback"]}]
            ]
        }
        send_telegram_message(chat_id, train_res["formatted_reply"], reply_markup=reply_markup)
        return {"status": "ok", "action": "train_tracked"}

    # Command: /pnr <10_digit_pnr>
    if text.startswith("/pnr"):
        query = text[4:].strip()
        if not query:
            send_telegram_message(
                chat_id,
                "🎫 *Please provide your 10-digit PNR number, for example:*\n"
                "`/pnr 2839182910`"
            )
            return {"status": "ok", "action": "sent_pnr_help"}
        pnr_res = track_train_status(query)
        reply_markup = {
            "inline_keyboard": [
                [{"text": "🔄 Refresh Live Status", "callback_data": pnr_res["refresh_callback"]}]
            ]
        }
        send_telegram_message(chat_id, pnr_res["formatted_reply"], reply_markup=reply_markup)
        return {"status": "ok", "action": "pnr_tracked"}

    # Command: /search <query>
    if text.startswith("/search"):
        query = text[7:].strip()
        if not query:
            send_telegram_message(
                chat_id,
                "💡 Please provide a search query, for example:\n"
                "`/search Top cafes in Hazratganj, Lucknow`"
            )
            return {"status": "ok", "action": "sent_search_help"}
        from app.search.agent import search_live_web
        search_res = search_live_web(query)
        send_telegram_message(chat_id, search_res["formatted_reply"])
        return {"status": "ok", "action": "live_search_performed"}

    # Command: /briefing (8:00 AM Morning Briefing on demand)
    if text.startswith("/briefing"):
        briefing_text = generate_morning_briefing()
        send_telegram_message(chat_id, briefing_text)
        return {"status": "ok", "action": "sent_briefing"}


    # Command: /meds (Today's Medication Status with interactive buttons)
    if text.startswith("/meds"):
        status_data = get_today_medication_status()
        items = status_data.get("items", [])

        if not items:
            send_telegram_message(
                chat_id,
                "💊 *No active medications scheduled for today.*\n\n"
                "To add a medicine, send a voice note or type:\n"
                "_\"Remind me to take Vitamin D 1000 IU every morning at 9 AM.\"_"
            )
            return {"status": "ok", "action": "sent_empty_meds"}

        lines = [
            f"💊 *Today's Medication Status ({status_data['date']})*",
            f"Adherence: *{status_data['taken_count']}/{status_data['total_count']} taken*",
            "",
        ]

        # Build buttons for any dose that hasn't been taken yet
        buttons = []
        for it in items:
            icon = "✅ Taken" if it["status"] == "taken" else "⏳ Pending" if it["status"] == "pending" else "⏰ Upcoming"
            taken_note = f" (at {it['taken_at']})" if it["taken_at"] else ""
            lines.append(f"• *{it['med_name']}* ({it['dosage']})\n  Scheduled: `{it['scheduled_time']}` | {icon}{taken_note}")

            if it["status"] != "taken":
                buttons.append([
                    {
                        "text": f"✅ Take {it['med_name']} ({it['scheduled_time']})",
                        "callback_data": f"take_med:{it['med_name']}:{it['scheduled_time']}",
                    },
                    {
                        "text": "⏰ Snooze",
                        "callback_data": f"snooze_med:{it['med_name']}:{it['scheduled_time']}",
                    }
                ])

        reply_markup = {"inline_keyboard": buttons} if buttons else None
        send_telegram_message(chat_id, "\n".join(lines), reply_markup=reply_markup)
        return {"status": "ok", "action": "sent_meds_status"}

    # Voice Note or Audio
    voice = message.get("voice") or message.get("audio")
    if voice:
        file_id = voice["file_id"]
        mime_type = voice.get("mime_type", "audio/ogg")
        send_telegram_message(chat_id, "🎧 *Listening to your voice note...*")

        audio_bytes = download_telegram_file(file_id)
        if not audio_bytes:
            send_telegram_message(chat_id, "❌ *Sorry, could not download voice file from Telegram.*")
            return {"status": "error", "reason": "download_failed"}

        # Route voice note: check if it's about medicine or general tasks
        result: VoiceExtractionResult = process_voice_or_text(
            audio_bytes=audio_bytes,
            mime_type=mime_type,
        )
        reply_body = format_telegram_reply(result)
        send_telegram_message(chat_id, reply_body)
        return {"status": "ok", "events_count": len(result.events), "tasks_count": len(result.tasks)}

    elif text:
        # Check if text is adding a medication
        med_keywords = ["medicine", "pill", "tablet", "dose", "antibiotic", "vitamin", "prescribe", "medication", "syrup"]
        if any(k in text.lower() for k in med_keywords) and ("remind" in text.lower() or "take" in text.lower()):
            med_result = process_medication_intake(text=text)
            buttons = []
            for m in med_result.medications:
                for t in m.times:
                    buttons.append([
                        {
                            "text": f"✅ Log {m.name} ({t}) as Taken",
                            "callback_data": f"take_med:{m.name}:{t}",
                        }
                    ])
            reply_markup = {"inline_keyboard": buttons} if buttons else None
            send_telegram_message(chat_id, med_result.confirmation_message, reply_markup=reply_markup)
            return {"status": "ok", "action": "medication_scheduled"}

        # Check if text is a flight query (e.g. "6E 204", "AI 432", "flight status")
        flight_pattern = r"\b(6E|AI|UK|SG|QP|G8|IX|I5|EK|QR|BA|LH|EY|FZ|TG|MH)\s*[- ]?\s*(\d{2,4})\b"
        if re.search(flight_pattern, text, re.IGNORECASE) or text.lower().startswith("flight"):
            flight_res = track_flight_status(text)
            reply_markup = {
                "inline_keyboard": [
                    [{"text": "🔄 Refresh Live Status", "callback_data": flight_res["refresh_callback"]}]
                ]
            }
            send_telegram_message(chat_id, flight_res["formatted_reply"], reply_markup=reply_markup)
            return {"status": "ok", "action": "flight_tracked"}

        # Check if text is a PNR or Train running status query
        pnr_match = re.search(r"\b\d{10}\b", text)
        is_train_query = (
            bool(pnr_match)
            or "pnr" in text.lower()
            or bool(re.search(r"\b\d{5}\b", text))
            or any(w in text.lower() for w in ["running status", "train status", "where is train", "vande bharat", "shatabdi", "rajdhani", "lucknow mail"])
        )
        if is_train_query and not any(k in text.lower() for k in ["remind", "medicine", "pill", "phone", "mobile"]):
            train_res = track_train_status(text)
            reply_markup = {
                "inline_keyboard": [
                    [{"text": "🔄 Refresh Live Status", "callback_data": train_res["refresh_callback"]}]
                ]
            }
            send_telegram_message(chat_id, train_res["formatted_reply"], reply_markup=reply_markup)
            return {"status": "ok", "action": "train_tracked"}

        # Check if text is a search query, local recommendation, or question
        search_triggers = ["find", "search", "who is", "who won", "what is", "where is", "how to", "best ", "top ", "recommend", "latest news", "tell me about"]
        is_search_intent = any(text.lower().startswith(trig) for trig in search_triggers) or (
            text.endswith("?") and not any(k in text.lower() for k in ["tomorrow", "pm", "am", "schedule", "remind", "at "])
        )
        if is_search_intent:
            from app.search.agent import search_live_web
            search_res = search_live_web(text)
            send_telegram_message(chat_id, search_res["formatted_reply"])
            return {"status": "ok", "action": "live_search_performed"}

        # Otherwise: General Voice/Text Task Extraction
        result = process_voice_or_text(text=text)
        reply_body = format_telegram_reply(result)
        send_telegram_message(chat_id, reply_body)
        return {"status": "ok", "events_count": len(result.events), "tasks_count": len(result.tasks)}


    send_telegram_message(chat_id, "💡 Please send a voice note or text message.")
    return {"status": "ignored"}


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
            cal_link = generate_google_calendar_url(ev.title, ev.start_time, ev.end_time, ev.description, ev.location)
            lines.append(f"• *{ev.title}*\n  ⏰ `{ev.start_time}`{loc}\n  👉 [Add to Google Calendar]({cal_link})")
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
