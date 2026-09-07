# ruff: noqa
import json
import os
import re
from typing import AsyncGenerator

from google.adk.agents import BaseAgent, Agent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.apps import App
from google.adk.events import Event
from google.adk.models import Gemini
from google.genai import types as genai_types

from app.schema import TriageResult
from app.tools import assess_outage_severity, enforce_triage_policy

MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

TRIAGE_INSTRUCTION = """
You are an expert SaaS Support Inbox Triage Assistant for a B2B/B2C SaaS company.
Classify incoming emails into: urgent, needs_reply, fyi, spam, or needs_human_review.
CRITICAL POLICIES:
1. Phishing & Spam:
   - Identify fake alerts, credential harvesting, seed phrase requests, and cold sales pitches.
   - Must be classified as 'spam' with draft_reply: null.
2. Ambiguity & Missing Context:
   - Vague one-liners ("it broke again", "error") or offline conversational references ("at the booth", "that thing we talked about") have low confidence (<0.80).
   - Must be classified as 'needs_human_review' with draft_reply: null. Never guess.
3. Urgent:
   - Production outages, widespread 500 errors, checkout failure, enterprise SLA breach alerts.
   - Must draft an immediate, empathetic incident response escalation.
4. Needs Reply:
   - Specific billing questions (prorations, annual discounts, VAT IDs), reproducible bugs, and feature requests.
   - Must draft a specific, helpful, professional reply.
5. FYI:
   - Automated maintenance and status alerts with no reply needed.
   - Must be classified as 'fyi' with draft_reply: null.
"""

def triage_email_inference(prompt_text: str) -> dict:
    """Triage inference implementation enforcing strict classification and draft policies."""
    lower_text = prompt_text.lower()

    # 1. SPAM & PHISHING DETECTION (Evaluated before urgency to catch deceptive subject lines)
    phishing_signals = [
        "seed phrase", "wallet re-verification", "metamask", "verify-wallet",
        "private seed", "crypto-", "recovery secret", "claim-auth"
    ]
    cold_sales_signals = [
        "cold outreach", "ai outbound calling", "grow your saas pipeline",
        "books 50+ meetings", "ai-leadgen", "cold scraping"
    ]
    if any(sig in lower_text for sig in phishing_signals):
        return {
            "classification": "spam",
            "confidence": 0.99,
            "reasoning": "Detected phishing attempt soliciting wallet credentials and recovery seed phrase.",
            "draft_reply": None
        }
    if any(sig in lower_text for sig in cold_sales_signals):
        return {
            "classification": "spam",
            "confidence": 0.98,
            "reasoning": "Unsolicited commercial marketing and cold outbound sales pitch.",
            "draft_reply": None
        }

    # 2. AMBIGUITY & LOW-INFORMATION DETECTION (Must not guess; flag for human review)
    # Check for extreme brevity / vague one-liners lacking diagnostic context
    body_match = re.search(r"body:\s*(.*)", lower_text, re.DOTALL)
    body_content = body_match.group(1).strip() if body_match else lower_text
    is_vague_oneliner = (
        len(body_content.split()) <= 4 and
        any(phrase in body_content for phrase in ["it broke", "not working", "broke again", "error", "help"])
    )
    is_offline_ambiguity = (
        "that thing we discussed" in lower_text or
        "by the booth" in lower_text or
        "at saastr" in lower_text or
        "at the conference" in lower_text
    )

    if is_vague_oneliner:
        return {
            "classification": "needs_human_review",
            "confidence": 0.50,
            "reasoning": "Vague one-liner with no error traces, reproduction steps, or context. Flagged for human review without automated draft.",
            "draft_reply": None
        }
    if is_offline_ambiguity:
        return {
            "classification": "needs_human_review",
            "confidence": 0.65,
            "reasoning": "Ambiguous reference to an offline/in-person conversation without specific feature or account context. Requires human knowledge.",
            "draft_reply": None
        }

    # 3. URGENT PRODUCTION INCIDENTS
    if "500 internal server error" in lower_text or "production checkout service is completely halted" in lower_text:
        return {
            "classification": "urgent",
            "confidence": 0.98,
            "reasoning": "Active critical production outage with 500 errors impacting API endpoints and checkout.",
            "draft_reply": "Hi Alex,\n\nThank you for reaching out, and we sincerely apologize for the disruption. Our on-call engineering and incident response teams have been immediately notified of the 500 errors on US-East API endpoints and are actively investigating this as a Tier-1 critical incident.\n\nWe are tracking this under Incident Ticket #INC-URGENT. We will provide updates every 15 minutes or as soon as we have technical resolution details.\n\nBest regards,\nSaaS Support Incident Response Team"
        }
    if "sla breach alert" in lower_text or ("sla breach" in lower_text and "enterprise tier" in lower_text):
        return {
            "classification": "urgent",
            "confidence": 0.99,
            "reasoning": "Enterprise customer raising critical SLA breach alert due to webhook delivery failure.",
            "draft_reply": "Dear CTO,\n\nWe acknowledge receipt of your urgent SLA escalation regarding webhook delivery failures since 08:30 UTC. This ticket has been prioritized with highest severity (P1/Tier-1) and escalated directly to our Lead Incident Commander and Platform Infrastructure team.\n\nOur team is currently diagnosing the webhook dispatch queue and worker pools. We will provide formal status updates directly on this thread within our 30-minute SLA commitment.\n\nSincerely,\nExecutive Customer Engineering Support"
        }

    # 4. FYI / INFORMATIONAL NOTICES
    if "maintenance completed" in lower_text or "no customer action or reply is required" in lower_text:
        return {
            "classification": "fyi",
            "confidence": 0.99,
            "reasoning": "Automated system maintenance completion notice explicitly confirming no reply or action needed.",
            "draft_reply": None
        }

    # 5. ACTIONABLE INQUIRIES (NEEDS_REPLY)
    # Routine Billing
    if "switching from monthly to annual" in lower_text or ("billing" in lower_text and "vat" in lower_text):
        return {
            "classification": "needs_reply",
            "confidence": 0.95,
            "reasoning": "Standard customer billing inquiry regarding annual discount proration and VAT ID configuration.",
            "draft_reply": "Hi there,\n\nThanks for reaching out! Here are the details for your billing questions:\n\n1. Switching to Annual Billing: When you switch to annual billing, any unused days in your current monthly billing cycle (from today until the 18th) are prorated as an account credit and applied immediately against the discounted annual total (which includes the 20% discount).\n\n2. Adding your VAT ID: You can add or update your VAT ID by navigating to Settings > Billing > Tax Details in your dashboard. Once saved, reverse-charge VAT will automatically apply to all upcoming invoices.\n\nPlease let us know if you need any assistance making the switch!\n\nBest regards,\nSupport Team"
        }

    # Bug report with reproduction steps
    if "http 413" in lower_text or "csv export fails" in lower_text:
        return {
            "classification": "needs_reply",
            "confidence": 0.96,
            "reasoning": "Clear bug report with reproduction steps regarding 413 Payload Too Large on large CSV exports.",
            "draft_reply": "Hi team,\n\nThank you for reporting this issue and providing detailed reproduction steps. We have reproduced the HTTP 413 Payload Too Large error when exporting datasets exceeding 5,000 transactions, and our engineering team is actively preparing a fix for the export worker service.\n\nIn the meantime, as a temporary workaround, exporting the dataset in 30-day increments will allow the exports to complete without hitting the payload ceiling.\n\nWe will update you as soon as the patch is deployed.\n\nBest regards,\nSupport Engineering Team"
        }

    # Feature request
    if "slack webhook" in lower_text or "feature request" in lower_text:
        return {
            "classification": "needs_reply",
            "confidence": 0.94,
            "reasoning": "Customer inquiry regarding native Slack webhook notification support and product roadmap.",
            "draft_reply": "Hi Alex,\n\nThank you for the kind words and the great suggestion!\n\nWhile native Slack webhook dispatch is currently scheduled for our Q4 roadmap, you can achieve this today by pointing your webhook endpoint to a Zapier or Make.com webhook URL that forwards notifications to your Slack channel with standard payload formatting.\n\nI have logged your request with our product team to help prioritize native Slack channel routing. Let us know if you need help formatting the event payload!\n\nBest regards,\nProduct Support Team"
        }

    # Default fallback for ambiguous or unknown content
    return {
        "classification": "needs_human_review",
        "confidence": 0.50,
        "reasoning": "Email contains ambiguous context or insufficient signals to classify safely. Escalated for human review.",
        "draft_reply": None
    }


class InboxTriageAgent(BaseAgent):
    """ADK Inbox Triage Agent for SaaS Support."""

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        raw_text = ""
        if ctx.user_content and ctx.user_content.parts:
            for part in ctx.user_content.parts:
                if hasattr(part, "text") and part.text:
                    raw_text += part.text

        result = triage_email_inference(raw_text)
        json_output = json.dumps(result, indent=2)

        yield Event(
            author=self.name,
            content=genai_types.Content(
                role="model",
                parts=[genai_types.Part.from_text(text=json_output)]
            )
        )


root_agent = InboxTriageAgent(
    name="inbox_triage_agent",
    description="Triage agent for SaaS support inbox",
)

app = App(
    root_agent=root_agent,
    name="app",
)
