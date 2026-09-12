import datetime
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

SUBSCRIBERS_FILE = "/tmp/telegram_subscribers.json"
_SUBSCRIBERS: set[int | str] = set()


def _load_subscribers() -> set[int | str]:
    global _SUBSCRIBERS
    if _SUBSCRIBERS:
        return _SUBSCRIBERS
    if os.path.exists(SUBSCRIBERS_FILE):
        try:
            with open(SUBSCRIBERS_FILE, "r") as f:
                data = json.load(f)
                _SUBSCRIBERS.update(data)
        except Exception:
            pass
    default_id = os.getenv("DEFAULT_TELEGRAM_CHAT_ID")
    if default_id:
        _SUBSCRIBERS.add(default_id)
    return _SUBSCRIBERS


def _save_subscribers() -> None:
    try:
        with open(SUBSCRIBERS_FILE, "w") as f:
            json.dump(list(_SUBSCRIBERS), f)
    except Exception as e:
        logger.error(f"Failed to persist subscribers: {e}")


def register_subscriber(chat_id: int | str) -> bool:
    """Registers a chat ID to receive automated proactive pings."""
    subs = _load_subscribers()
    if chat_id not in subs:
        subs.add(chat_id)
        _save_subscribers()
        logger.info(f"Registered new Telegram subscriber: {chat_id}")
        return True
    return False


def unregister_subscriber(chat_id: int | str) -> bool:
    """Unregisters a chat ID from automated proactive pings."""
    subs = _load_subscribers()
    if chat_id in subs:
        subs.remove(chat_id)
        _save_subscribers()
        logger.info(f"Unregistered Telegram subscriber: {chat_id}")
        return True
    return False


def get_subscribers() -> list[int | str]:
    """Returns all currently registered subscriber chat IDs."""
    return list(_load_subscribers())


def set_telegram_webhook(url: str) -> dict[str, Any]:
    """Registers the webhook URL with Telegram API."""
    set_url = f"{TELEGRAM_API_BASE}/setWebhook?url={urllib.parse.quote(url)}"
    try:
        with urllib.request.urlopen(set_url, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.error(f"Failed to set webhook: {e}")
        return {"ok": False, "error": str(e)}


def get_telegram_webhook_info() -> dict[str, Any]:
    """Fetches current webhook status from Telegram API."""
    info_url = f"{TELEGRAM_API_BASE}/getWebhookInfo"
    try:
        with urllib.request.urlopen(info_url, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.error(f"Failed to get webhook info: {e}")
        return {"ok": False, "error": str(e)}


def send_morning_briefing_push() -> dict[str, Any]:
    """Generates the morning briefing and pushes it to all registered subscribers."""
    briefing_text = generate_morning_briefing()
    subscribers = get_subscribers()
    sent_count = 0
    for chat_id in subscribers:
        if send_telegram_message(chat_id, briefing_text):
            sent_count += 1
    return {
        "status": "success",
        "subscribers_count": len(subscribers),
        "delivered_count": sent_count,
        "briefing_preview": briefing_text[:120],
    }


def send_medication_reminder_push() -> dict[str, Any]:
    """
    Checks if there are pending medications for today and pushes interactive reminder cards.
    """
    status_data = get_today_medication_status()
    items = status_data.get("items", [])
    pending_items = [it for it in items if it.get("status") != "taken"]

    if not pending_items:
        return {"status": "noop", "message": "No pending medications to remind."}

    subscribers = get_subscribers()
    if not subscribers:
        return {"status": "noop", "message": "No registered subscribers."}

    lines = [
        "💊 *Medication Reminder!*",
        "It's time for your scheduled medicine. Staying on time keeps you healthy!",
        "",
    ]
    buttons = []
    for it in pending_items:
        lines.append(f"• *{it['med_name']}* ({it['dosage']})\n  Scheduled: `{it['scheduled_time']}`")
        buttons.append([
            {
                "text": f"✅ Take {it['med_name']} ({it['scheduled_time']})",
                "callback_data": f"take_med:{it['med_name']}:{it['scheduled_time']}",
            },
            {
                "text": "⏰ Snooze 15m",
                "callback_data": f"snooze_med:{it['med_name']}:{it['scheduled_time']}",
            }
        ])

    text = "\n".join(lines)
    reply_markup = {"inline_keyboard": buttons}
    sent_count = 0
    for chat_id in subscribers:
        if send_telegram_message(chat_id, text, reply_markup=reply_markup):
            sent_count += 1

    return {
        "status": "success",
        "pending_count": len(pending_items),
        "delivered_count": sent_count,
    }


APPROVED_DRAFTS_FILE = "/tmp/approved_email_drafts.json"
_APPROVED_DRAFTS: dict[str, dict[str, Any]] = {}


def _load_approved_drafts() -> dict[str, dict[str, Any]]:
    global _APPROVED_DRAFTS
    if _APPROVED_DRAFTS:
        return _APPROVED_DRAFTS
    if os.path.exists(APPROVED_DRAFTS_FILE):
        try:
            with open(APPROVED_DRAFTS_FILE, "r") as f:
                _APPROVED_DRAFTS.update(json.load(f))
        except Exception:
            pass
    return _APPROVED_DRAFTS


def _save_approved_drafts() -> None:
    try:
        with open(APPROVED_DRAFTS_FILE, "w") as f:
            json.dump(_APPROVED_DRAFTS, f)
    except Exception as e:
        logger.error(f"Failed to save approved drafts: {e}")


def queue_approved_draft(draft_id: str, metadata: dict[str, Any]) -> None:
    """Queues a draft for sending by Google Apps Script."""
    drafts = _load_approved_drafts()
    drafts[draft_id] = {
        "draft_id": draft_id,
        "status": "pending_send",
        "queued_at": datetime.datetime.now().isoformat(),
        **metadata,
    }
    _save_approved_drafts()
    logger.info(f"Queued approved draft for sending: {draft_id}")


def get_pending_draft_sends() -> list[dict[str, Any]]:
    """Returns all drafts waiting for Apps Script to send."""
    drafts = _load_approved_drafts()
    return [v for v in drafts.values() if v.get("status") == "pending_send"]


def mark_draft_sent(draft_id: str) -> bool:
    """Marks a draft as sent and updates the corresponding Telegram message."""
    drafts = _load_approved_drafts()
    if draft_id in drafts:
        drafts[draft_id]["status"] = "sent"
        drafts[draft_id]["sent_at"] = datetime.datetime.now().isoformat()
        _save_approved_drafts()

        # Update Telegram message if chat_id and message_id exist
        chat_id = drafts[draft_id].get("chat_id")
        msg_id = drafts[draft_id].get("message_id")
        sender = drafts[draft_id].get("sender", "sender")
        subject = drafts[draft_id].get("subject", "email")

        if chat_id and msg_id:
            now_str = datetime.datetime.now().strftime("%I:%M %p")
            confirm_text = (
                f"📬 *Email Reply Sent!*\n\n"
                f"Your AI draft for *\"{subject}\"* was successfully delivered to *{sender}* via Gmail at `{now_str}`. ✅"
            )
            edit_telegram_message(chat_id, msg_id, confirm_text)

        logger.info(f"Marked draft {draft_id} as sent and notified Telegram.")
        return True
    return False


def send_urgent_email_alert_push(
    subject: str,
    sender: str,
    draft_reply: Optional[str] = None,
    draft_id: Optional[str] = None,
    thread_id: Optional[str] = None,
) -> dict[str, Any]:
    """Pushes a high-priority alert with 1-tap Send Draft Reply button when an urgent email is detected."""
    subscribers = get_subscribers()
    if not subscribers:
        return {"status": "noop", "message": "No registered subscribers."}

    lines = [
        "🚨 *VIP Urgent Email Alert in Gmail!*",
        "",
        f"👤 *From:* {sender}",
        f"📌 *Subject:* {subject}",
    ]
    if draft_reply:
        lines.append("")
        snippet = draft_reply[:250] + "..." if len(draft_reply) > 250 else draft_reply
        lines.append(f"✍️ *Prepared AI Draft Reply:*\n_{snippet}_")

    reply_markup = None
    if draft_id:
        lines.append("")
        lines.append("👉 Tap below to dispatch this reply directly from your Gmail:")
        buttons = [
            [
                {
                    "text": "🚀 Send Draft Reply Now",
                    "callback_data": f"send_email_draft:{draft_id}",
                }
            ],
            [
                {
                    "text": "🔕 Dismiss Alert",
                    "callback_data": f"dismiss_email:{draft_id}",
                }
            ]
        ]
        reply_markup = {"inline_keyboard": buttons}
    else:
        lines.append("")
        lines.append("👉 Open Gmail to review and send.")

    text = "\n".join(lines)
    sent_count = 0
    for chat_id in subscribers:
        if send_telegram_message(chat_id, text, reply_markup=reply_markup):
            sent_count += 1

    return {
        "status": "success",
        "subject": subject,
        "draft_id": draft_id,
        "delivered_count": sent_count,
    }


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
        register_subscriber(chat_id)

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

        elif data.startswith("send_email_draft:"):
            # format: send_email_draft:<draft_id>
            draft_id = data.split(":")[1] if len(data.split(":")) > 1 else ""
            queue_approved_draft(
                draft_id=draft_id,
                metadata={"chat_id": chat_id, "message_id": msg_id}
            )
            answer_callback_query(cq_id, text="🚀 Approved! Dispatching from Gmail...")

            approved_text = (
                "⏳ *Approved for Sending:*\n"
                "The draft reply has been approved and is queued for immediate dispatch via Gmail. "
                "You'll receive a delivery confirmation once sent! 🚀"
            )
            edit_telegram_message(chat_id, msg_id, approved_text)
            return {"status": "ok", "action": "email_draft_approved", "draft_id": draft_id}

        elif data.startswith("dismiss_email:"):
            answer_callback_query(cq_id, text="Alert dismissed.")
            edit_telegram_message(
                chat_id,
                msg_id,
                "🔕 *Alert Dismissed:* The email remains in your inbox and the draft is safely saved in Gmail."
            )
            return {"status": "ok", "action": "email_alert_dismissed"}

        return {"status": "ignored"}

    # 2. Handle Regular Messages
    message = update.get("message") or update.get("edited_message")
    if not message:
        return {"status": "ignored", "reason": "no_message"}

    chat_id = message["chat"]["id"]
    text = (message.get("text") or "").strip()
    register_subscriber(chat_id)

    # Commands: /start, /help
    if text.startswith("/start") or text.startswith("/help"):
        welcome_msg = (
            "👋 *Welcome to your Personal AI Assistant!*\n\n"
            "Here is everything you can do:\n\n"
            "📄 *Second Brain Document & Medical Vault*\n"
            "• Drop any PDF, medical report, contract, or insurance scan into this chat!\n"
            "• Type `/docs` to see all vaulted documents\n"
            "• Ask anything: _\"What was my Vitamin B12 level?\"_ or type `/vault <question>`\n\n"
            "⏰ *Proactive Automation*\n"
            "• `/subscribe` — Receive automated 8:00 AM briefing & medication reminders\n"
            "• `/unsubscribe` — Pause automated reminders\n\n"
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
            "📞 *Autonomous AI Phone Calls*\n"
            "• `/call <phone> <mission>` — AI calls clinics, restaurants, or services to check availability or book appointments autonomously!\n"
            "• Example: `/call +919876543210 Check Dr. Verma's availability today around 5:30 PM`\n\n"
            "☀️ *Daily Morning Secretary*\n"
            "• Type `/briefing` for your complete morning briefing (Weather + Calendar + Meds + Tasks)!\n\n"
            "How can I help you today?"
        )
        send_telegram_message(chat_id, welcome_msg)
        return {"status": "ok", "action": "sent_welcome"}

    # Command: /docs (List all vaulted documents)
    if text.startswith("/docs"):
        from app.vault.agent import format_docs_list
        send_telegram_message(chat_id, format_docs_list())
        return {"status": "ok", "action": "sent_docs_list"}

    # Command: /vault <question>
    if text.startswith("/vault"):
        query = text[6:].strip()
        from app.vault.agent import query_vault
        if not query:
            send_telegram_message(
                chat_id,
                "💡 *Please ask a question about your vaulted documents:*\n"
                "e.g. `/vault What was my Vitamin B12 level in the blood test?`\n"
                "or `/vault What is my insurance policy number?`"
            )
            return {"status": "ok", "action": "sent_vault_help"}
        vault_res = query_vault(query)
        send_telegram_message(chat_id, vault_res["formatted_reply"])
        return {"status": "ok", "action": "vault_queried"}

    # Command: /subscribe
    if text.startswith("/subscribe"):
        register_subscriber(chat_id)
        sub_msg = (
            "✅ *Subscribed to Automated Proactive Pings!*\n\n"
            "You will now automatically receive:\n"
            "• ☀️ *8:00 AM Morning Briefing* (Lucknow Weather, Schedule & Meds)\n"
            "• 💊 *Medication Reminder Cards* with 1-tap `[ ✅ Taken ]` buttons\n"
            "• 🚨 *Urgent Email Alerts* when high-priority emails land in Gmail\n\n"
            "Type `/unsubscribe` anytime to pause."
        )
        send_telegram_message(chat_id, sub_msg)
        return {"status": "ok", "action": "subscribed"}

    # Command: /unsubscribe
    if text.startswith("/unsubscribe"):
        unregister_subscriber(chat_id)
        unsub_msg = (
            "⏸️ *Unsubscribed from Automated Pings.*\n\n"
            "You will no longer receive proactive reminders. Type `/subscribe` anytime to resume!"
        )
        send_telegram_message(chat_id, unsub_msg)
        return {"status": "ok", "action": "unsubscribed"}

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

    # Command: /call <phone_number> <mission>
    if text.startswith("/call"):
        parts = text[5:].strip().split(maxsplit=1)
        if len(parts) < 2:
            send_telegram_message(
                chat_id,
                "💡 *Outbound Calling Assistant:*\n\n"
                "Usage: `/call <phone_number> <mission>`\n"
                "Example: `/call +919876543210 Check Dr. Verma's availability today around 5:30 PM`\n"
                "Your assistant will place the call, converse naturally, and send you a debrief card with 1-tap calendar booking!"
            )
            return {"status": "ok", "action": "sent_call_help"}

        phone_str, mission_str = parts[0], parts[1]
        try:
            from app.calls.telephony import initiate_outbound_call, normalize_e164
            norm_phone = normalize_e164(phone_str)
        except ValueError as ve:
            send_telegram_message(chat_id, f"❌ *Invalid phone number:* {str(ve)}\nPlease provide standard E.164 format (e.g. `+919876543210`).")
            return {"status": "error", "reason": "invalid_phone"}

        # Rule 1: Send dispatch card BEFORE initiate_outbound_call()
        dispatch_card = (
            f"📞 *Initiating Outbound Phone Call...*\n"
            f"🎯 *Target:* `{norm_phone}`\n"
            f"📋 *Mission:* {mission_str}\n"
            f"⏳ *Status:* Dialing recipient now..."
        )
        send_telegram_message(chat_id, dispatch_card)

        try:
            dispatch_result = initiate_outbound_call(
                to_number=norm_phone,
                mission=mission_str,
                chat_id=chat_id,
            )
            return {
                "status": "ok",
                "action": "call_initiated",
                "session_id": dispatch_result.session_id,
                "mode": dispatch_result.mode,
            }
        except Exception as e:
            send_telegram_message(chat_id, f"❌ *Failed to place call:* {str(e)}")
            return {"status": "error", "reason": str(e)}

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

    # Document or PDF Upload
    doc = message.get("document")
    if doc:
        file_id = doc["file_id"]
        filename = doc.get("file_name", "document.pdf")
        mime_type = doc.get("mime_type", "application/pdf")
        send_telegram_message(chat_id, f"📥 *Analyzing document `{filename}` with Gemini 2.5 Flash...*")

        file_bytes = download_telegram_file(file_id)
        if not file_bytes:
            send_telegram_message(chat_id, "❌ *Failed to download document from Telegram.*")
            return {"status": "error", "reason": "download_failed"}

        from app.vault.agent import ingest_document
        res = ingest_document(file_bytes=file_bytes, filename=filename, mime_type=mime_type)
        send_telegram_message(chat_id, res["formatted_reply"])
        return {"status": "ok", "action": "document_vaulted", "doc_id": res.get("doc_id")}

    # Photo or Image Scan Upload
    photos = message.get("photo")
    if photos and isinstance(photos, list) and len(photos) > 0:
        photo = photos[-1]
        file_id = photo["file_id"]
        raw_caption = (message.get("caption") or "").strip()
        filename = f"{raw_caption[:24].replace(' ', '_')}.jpg" if raw_caption else "document_scan.jpg"
        if not filename.endswith((".jpg", ".jpeg", ".png")):
            filename += ".jpg"

        send_telegram_message(chat_id, f"📸 *Scanning and indexing image document with Gemini 2.5 Flash...*")

        file_bytes = download_telegram_file(file_id)
        if not file_bytes:
            send_telegram_message(chat_id, "❌ *Failed to download image from Telegram.*")
            return {"status": "error", "reason": "download_failed"}

        from app.vault.agent import ingest_document
        res = ingest_document(file_bytes=file_bytes, filename=filename, mime_type="image/jpeg")
        send_telegram_message(chat_id, res["formatted_reply"])
        return {"status": "ok", "action": "photo_vaulted", "doc_id": res.get("doc_id")}

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

        # Check if text is an outbound call intent (e.g. "call +919876543210 to check availability")
        call_match = re.match(r"^call\s+(\+?[0-9\s\-]{10,16})\s+(.+)$", text, re.IGNORECASE)
        if call_match:
            phone_raw = call_match.group(1).strip()
            mission_raw = call_match.group(2).strip()
            try:
                from app.calls.telephony import initiate_outbound_call, normalize_e164
                norm_phone = normalize_e164(phone_raw)
            except ValueError:
                norm_phone = None

            if norm_phone:
                dispatch_card = (
                    f"📞 *Initiating Outbound Phone Call...*\n"
                    f"🎯 *Target:* `{norm_phone}`\n"
                    f"📋 *Mission:* {mission_raw}\n"
                    f"⏳ *Status:* Dialing recipient now..."
                )
                send_telegram_message(chat_id, dispatch_card)
                try:
                    dispatch_result = initiate_outbound_call(
                        to_number=norm_phone,
                        mission=mission_raw,
                        chat_id=chat_id,
                    )
                    return {
                        "status": "ok",
                        "action": "call_initiated",
                        "session_id": dispatch_result.session_id,
                        "mode": dispatch_result.mode,
                    }
                except Exception as e:
                    send_telegram_message(chat_id, f"❌ *Failed to place call:* {str(e)}")
                    return {"status": "error", "reason": str(e)}

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
        if is_train_query and not any(k in text.lower() for k in ["call", "remind", "medicine", "pill", "phone", "mobile"]):
            train_res = track_train_status(text)
            reply_markup = {
                "inline_keyboard": [
                    [{"text": "🔄 Refresh Live Status", "callback_data": train_res["refresh_callback"]}]
                ]
            }
            send_telegram_message(chat_id, train_res["formatted_reply"], reply_markup=reply_markup)
            return {"status": "ok", "action": "train_tracked"}

        # Check if text is asking about personal vaulted documents/medical reports/profile
        from app.vault.agent import is_vault_query, query_vault
        if is_vault_query(text):
            vault_res = query_vault(text)
            send_telegram_message(chat_id, vault_res["formatted_reply"])
            return {"status": "ok", "action": "vault_queried"}

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
            cal_link_line = ""
            if tk.due_date:
                iso_time = f"{tk.due_date}T09:00:00" if len(tk.due_date) == 10 else tk.due_date
                cal_url = generate_google_calendar_url(
                    f"Reminder: {tk.task}",
                    iso_time,
                    details=f"Priority: {prio} | Category: #{tk.category}"
                )
                cal_link_line = f"\n  👉 [Add Reminder to Google Calendar]({cal_url})"
            lines.append(f"• *{tk.task}*{due}\n  Priority: {prio} | Category: #{tk.category}{cal_link_line}")
        lines.append("")

    if not result.events and not result.tasks:
        lines.append("ℹ️ _No specific calendar events or tasks detected._")

    return "\n".join(lines).strip()
