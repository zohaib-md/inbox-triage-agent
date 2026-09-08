import logging
import os
from typing import Any, Optional

logger = logging.getLogger("search_agent")
MODEL_NAME = os.getenv("SEARCH_AGENT_MODEL", "gemini-2.5-flash")
DEFAULT_LOCATION = os.getenv("USER_CITY", "Lucknow")

SEARCH_SYSTEM_INSTRUCTION = """You are a helpful, knowledgeable real-time research and local scout assistant.
You have access to real-time Google Search.
Your job is to answer the user's query accurately using the latest facts from the web.
- If the user asks about local places (restaurants, cafes, spots, clinics, shops), give specific recommendations with neighborhoods (e.g. Hazratganj, Gomti Nagar, Aliganj in Lucknow) and price/rating highlights.
- If the user asks about live events, news, or sports, provide current factual details.
- Keep answers concise, highly readable with bullet points and bold titles, formatted in Telegram Markdown.
- Keep it under 250 words so it is easy to read on mobile.
"""


def search_live_web(query: str, user_location: str = DEFAULT_LOCATION) -> dict[str, Any]:
    """
    Executes a real-time grounded search using Gemini 2.5 Flash and Google Search Grounding.
    Returns the synthesized text, bullet points, and source citations.
    """
    try:
        from google import genai
        from google.genai import types

        client = genai.Client()
        prompt = f"User is located in or asking about {user_location}. Query: {query}"

        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SEARCH_SYSTEM_INSTRUCTION,
                tools=[types.Tool(google_search=types.GoogleSearch())],
                temperature=0.3,
            ),
        )

        answer_text = (response.text or "").strip()

        # Extract web source links from grounding metadata
        sources = []
        try:
            candidate = response.candidates[0]
            metadata = candidate.grounding_metadata
            if metadata and metadata.grounding_chunks:
                for chunk in metadata.grounding_chunks:
                    if chunk.web and chunk.web.uri:
                        title = chunk.web.title or "Source"
                        uri = chunk.web.uri
                        if not any(s["uri"] == uri for s in sources):
                            sources.append({"title": title[:30], "uri": uri})
        except Exception:
            pass

        formatted_reply = _format_search_reply(query, answer_text, sources[:4])
        return {
            "status": "success",
            "query": query,
            "answer": answer_text,
            "sources": sources,
            "formatted_reply": formatted_reply,
        }

    except Exception as e:
        logger.error(f"Error in search_live_web: {e}")
        return _fallback_search_reply(query, user_location, str(e))


def _format_search_reply(query: str, answer_text: str, sources: list[dict[str, str]]) -> str:
    """Formats the answer and citations into a clean Telegram Markdown message."""
    lines = [
        f"🔍 *Search Results:* \"{query}\"",
        "",
        answer_text,
    ]

    if sources:
        lines.append("")
        lines.append("🌐 *Sources:*")
        for s in sources:
            lines.append(f"• [{s['title']}]({s['uri']})")

    return "\n".join(lines).strip()


def _fallback_search_reply(query: str, user_location: str, error_msg: str) -> dict[str, Any]:
    """Offline heuristic fallback for testing or when external API is unreachable."""
    answer = (
        f"Here are results for *{query}* in *{user_location}*:\n\n"
        f"• Recommended popular spots and information matching your search.\n"
        f"• For full live details, verify directly with local business listings."
    )
    return {
        "status": "fallback",
        "query": query,
        "answer": answer,
        "sources": [{"title": "Google Search", "uri": f"https://www.google.com/search?q={query}"}],
        "formatted_reply": f"🔍 *Search:* \"{query}\"\n\n{answer}",
    }
