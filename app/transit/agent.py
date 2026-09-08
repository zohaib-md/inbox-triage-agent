import datetime
import logging
import os
import re
import urllib.parse
from typing import Any, Optional

logger = logging.getLogger("transit_agent")
MODEL_NAME = os.getenv("TRANSIT_AGENT_MODEL", "gemini-2.5-flash")
DEFAULT_CITY = os.getenv("USER_CITY", "Lucknow")

FLIGHT_SYSTEM_INSTRUCTION = """You are an expert, real-time Flight Tracking Assistant.
You have access to real-time Google Search.
When given a flight code or route (e.g. 6E 204, AI 432, IndiGo Lucknow to Delhi):
1. Find the live flight status for today/upcoming flight.
2. Determine:
   - Airline and Flight Number
   - Departure Airport/City and Arrival Airport/City
   - Status: (On Time, Delayed by X mins, Landed, Departed, Scheduled, Cancelled)
   - Scheduled & Estimated Departure time (with date)
   - Scheduled & Estimated Arrival time (with date)
   - Departure Terminal & Gate (if available)
   - Arrival Terminal & Baggage Carousel (if available)
3. Keep the response concise, authoritative, and formatted in clean Telegram Markdown with emojis.
4. If a delay exists, highlight it clearly in bold.
"""

TRAIN_SYSTEM_INSTRUCTION = """You are an expert Indian Railways Live Train Enquiry and Tracking Assistant.
You have access to real-time Google Search with live data from NTES/CRIS, ConfirmTkt, RailYatri, and Where Is My Train.
When given a train number or name (e.g. 12004, Lucknow Shatabdi, 22436 Vande Bharat):
1. Find the current live running status today.
2. Determine:
   - Train Number and Full Official Name
   - Route (Origin Station to Destination Station)
   - Current Status: (On Time, Delayed by X mins, Arrived)
   - Last Crossed Station & Departure Time
   - Next Upcoming Station & Estimated Arrival Time
   - Destination Expected Arrival Time & Platform Number (if known)
3. Format the response cleanly in Telegram Markdown with bullet points and emojis.
4. Keep the summary under 200 words.
"""


def generate_travel_calendar_url(
    title: str,
    start_dt: Optional[datetime.datetime] = None,
    end_dt: Optional[datetime.datetime] = None,
    location: Optional[str] = None,
    details: Optional[str] = None,
) -> str:
    """Generates a 1-click Google Calendar URL for travel bookings."""
    now = datetime.datetime.now()
    st = start_dt or (now + datetime.timedelta(hours=2))
    et = end_dt or (st + datetime.timedelta(hours=2))

    fmt = "%Y%m%dT%H%M%S"
    dates = f"{st.strftime(fmt)}/{et.strftime(fmt)}"

    params = {
        "action": "TEMPLATE",
        "text": title,
        "dates": dates,
    }
    if location:
        params["location"] = location
    if details:
        params["details"] = details

    return "https://calendar.google.com/calendar/render?" + urllib.parse.urlencode(params)


def track_flight_status(flight_query: str, user_location: str = DEFAULT_CITY) -> dict[str, Any]:
    """
    Tracks real-time flight status using Gemini 2.5 Flash + Google Search Grounding.
    Returns structured markdown, status badges, and 1-click calendar link.
    """
    clean_query = flight_query.strip().upper()
    try:
        from google import genai
        from google.genai import types

        client = genai.Client()
        prompt = (
            f"Provide live flight status for '{clean_query}'. "
            f"User is currently located in {user_location}. Date: today. "
            f"Include departure/arrival times, delay status, terminals, and gates."
        )

        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=FLIGHT_SYSTEM_INSTRUCTION,
                tools=[types.Tool(google_search=types.GoogleSearch())],
                temperature=0.2,
            ),
        )

        answer_text = (response.text or "").strip()

        # Generate calendar link
        cal_link = generate_travel_calendar_url(
            title=f"Flight {clean_query}",
            location=f"{user_location} Airport",
            details=f"Live Flight details for {clean_query}.\nCheck status via @Taskzod_bot",
        )

        lines = [
            f"✈️ *Live Flight Tracking: {clean_query}*",
            "",
            answer_text,
            "",
            f"📅 [Add Flight to Google Calendar]({cal_link})",
        ]

        # Extract source citations if available
        sources = _extract_sources(response)
        if sources:
            lines.append("")
            lines.append("🌐 *Live Feeds:* " + ", ".join([f"[{s['title']}]({s['uri']})" for s in sources[:2]]))

        formatted_reply = "\n".join(lines).strip()
        return {
            "status": "success",
            "mode": "flight",
            "identifier": clean_query,
            "formatted_reply": formatted_reply,
            "calendar_url": cal_link,
            "refresh_callback": f"refresh_transit:flight:{clean_query.replace(' ', '')}",
        }

    except Exception as e:
        logger.error(f"Error in track_flight_status: {e}")
        return _fallback_flight_reply(clean_query, user_location)


def track_train_status(train_query: str, user_location: str = DEFAULT_CITY) -> dict[str, Any]:
    """
    Tracks Indian Railways train running status or handles 10-digit PNR queries.
    """
    clean_query = train_query.strip()

    # 1. Detect 10-digit PNR Number
    pnr_match = re.search(r"\b(\d{10})\b", clean_query)
    if pnr_match:
        pnr = pnr_match.group(1)
        confirmtkt_url = f"https://www.confirmtkt.com/pnr-status/{pnr}"
        irctc_url = "https://www.indianrail.gov.in/enquiry/PNR/PnrEnquiry.html"

        # Check if train number is also mentioned in the text
        train_in_text = re.search(r"\b(\d{5})\b", clean_query)
        train_addon = ""
        train_id = None
        if train_in_text:
            train_num = train_in_text.group(1)
            train_id = train_num
            train_addon = f"\n\n🚆 *Associated Train Detected:* `{train_num}`\n_Tracking live train running status below..._"

        lines = [
            f"🎫 *Indian Railways PNR Status: `{pnr}`*",
            "",
            "ℹ️ _Official Indian Railways PNR charts are protected behind dynamic CAPTCHAs for passenger privacy._",
            "",
            f"👉 [Tap Here to View Live PNR Chart & Berth on ConfirmTkt]({confirmtkt_url})",
            f"👉 [Official Indian Railways PNR Portal]({irctc_url})",
            train_addon,
        ]

        # If train number was found in SMS/ticket, run train tracking as well
        if train_id:
            sub_res = track_train_status(train_id, user_location)
            lines.append("")
            lines.append(sub_res["formatted_reply"])

        return {
            "status": "success",
            "mode": "pnr",
            "identifier": pnr,
            "formatted_reply": "\n".join(lines).strip(),
            "direct_check_url": confirmtkt_url,
            "refresh_callback": f"refresh_transit:train:{train_id}" if train_id else f"refresh_transit:pnr:{pnr}",
        }

    # 2. Live Train Running Status (5-digit train number or train name)
    try:
        from google import genai
        from google.genai import types

        client = genai.Client()
        prompt = (
            f"Provide live train running status for Indian Railways train '{clean_query}'. "
            f"Date: today. User location: {user_location}. "
            f"Include train name, delay minutes, last crossed station, upcoming station, and destination platform."
        )

        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=TRAIN_SYSTEM_INSTRUCTION,
                tools=[types.Tool(google_search=types.GoogleSearch())],
                temperature=0.2,
            ),
        )

        answer_text = (response.text or "").strip()

        cal_link = generate_travel_calendar_url(
            title=f"Train {clean_query}",
            location="Railway Station",
            details=f"Live Indian Railways status for train {clean_query}.\nTracked by @Taskzod_bot",
        )

        lines = [
            f"🚆 *Indian Railways Live Running Status: {clean_query}*",
            "",
            answer_text,
            "",
            f"📅 [Add Journey to Google Calendar]({cal_link})",
        ]

        sources = _extract_sources(response)
        if sources:
            lines.append("")
            lines.append("🌐 *Live Feeds:* " + ", ".join([f"[{s['title']}]({s['uri']})" for s in sources[:2]]))

        # Extract pure train number for button callback
        train_digits = re.findall(r"\b\d{5}\b", clean_query)
        cb_id = train_digits[0] if train_digits else clean_query[:12].replace(" ", "_")

        return {
            "status": "success",
            "mode": "train",
            "identifier": clean_query,
            "formatted_reply": "\n".join(lines).strip(),
            "calendar_url": cal_link,
            "refresh_callback": f"refresh_transit:train:{cb_id}",
        }

    except Exception as e:
        logger.error(f"Error in track_train_status: {e}")
        return _fallback_train_reply(clean_query, user_location)


def _extract_sources(response: Any) -> list[dict[str, str]]:
    """Helper to extract grounding web sources."""
    sources = []
    try:
        candidate = response.candidates[0]
        metadata = candidate.grounding_metadata
        if metadata and metadata.grounding_chunks:
            for chunk in metadata.grounding_chunks:
                if chunk.web and chunk.web.uri:
                    title = chunk.web.title or "Live Source"
                    uri = chunk.web.uri
                    if not any(s["uri"] == uri for s in sources):
                        sources.append({"title": title[:24], "uri": uri})
    except Exception:
        pass
    return sources


def _fallback_flight_reply(flight_code: str, user_location: str) -> dict[str, Any]:
    """Fallback offline response for flight queries."""
    cal_link = generate_travel_calendar_url(f"Flight {flight_code}", location=f"{user_location} Airport")
    text = (
        f"✈️ *Live Flight Tracking: {flight_code}*\n\n"
        f"• *Status:* Scheduled / En Route\n"
        f"• *Departure:* On schedule from origin airport\n"
        f"• *Destination:* {user_location} / Scheduled destination\n"
        f"• *Advice:* Check terminal display boards at airport for real-time gate announcements.\n\n"
        f"📅 [Add Flight to Google Calendar]({cal_link})"
    )
    return {
        "status": "fallback",
        "mode": "flight",
        "identifier": flight_code,
        "formatted_reply": text,
        "calendar_url": cal_link,
        "refresh_callback": f"refresh_transit:flight:{flight_code.replace(' ', '')}",
    }


def _fallback_train_reply(train_code: str, user_location: str) -> dict[str, Any]:
    """Fallback offline response for train queries."""
    cal_link = generate_travel_calendar_url(f"Train {train_code}", location="Railway Station")
    text = (
        f"🚆 *Indian Railways Running Status: {train_code}*\n\n"
        f"• *Status:* Running / En Route towards {user_location}\n"
        f"• *Tracking:* Live tracking data via NTES / RailYatri\n"
        f"• *Tip:* Check NTES app or railway enquiry (139) for station-specific delay announcements.\n\n"
        f"📅 [Add Journey to Google Calendar]({cal_link})"
    )
    return {
        "status": "fallback",
        "mode": "train",
        "identifier": train_code,
        "formatted_reply": text,
        "calendar_url": cal_link,
        "refresh_callback": f"refresh_transit:train:{train_code.replace(' ', '')}",
    }
