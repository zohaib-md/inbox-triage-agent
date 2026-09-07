"""ADK tools for SaaS inbox triage and policy enforcement."""

def assess_outage_severity(subject: str, body: str) -> dict:
    """Evaluates whether an email describes an active outage, critical SLA breach, or system failure.

    Args:
        subject: The subject line of the email.
        body: The message body.

    Returns:
        A dict with outage indicators, recommended priority, and suggested escalation level.
    """
    text = (subject + " " + body).lower()
    urgent_signals = [
        "outage", "down", "500", "server error", "sla breach",
        "production halted", "critical", "incident", "cannot checkout", "failing"
    ]
    matches = [signal for signal in urgent_signals if signal in text]
    is_urgent = len(matches) >= 2 or "outage" in text or "sla breach" in text

    return {
        "detected_signals": matches,
        "is_urgent_candidate": is_urgent,
        "recommended_priority": "P1" if is_urgent else "Standard"
    }


def enforce_triage_policy(
    classification: str,
    confidence: float,
    has_draft_reply: bool
) -> dict:
    """Verifies that the triage output adheres to SaaS inbox policy guardrails.

    Policy rules:
    - If confidence < 0.80 or email is ambiguous, MUST be 'needs_human_review'.
    - If 'spam', 'fyi', or 'needs_human_review', draft_reply MUST be None (no auto reply).
    - If 'urgent' or 'needs_reply', draft_reply MUST be provided.

    Args:
        classification: The candidate classification.
        confidence: The confidence score from 0.0 to 1.0.
        has_draft_reply: Whether a suggested reply was drafted.

    Returns:
        A dict with policy_valid boolean, final_classification, and any policy notes.
    """
    final_class = classification
    notes = []

    # Rule 1: Low confidence or ambiguous
    if confidence < 0.80 and classification != "needs_human_review":
        final_class = "needs_human_review"
        notes.append("Overridden to 'needs_human_review' due to low confidence (<0.80).")

    # Rule 2: No drafts for spam/fyi/needs_human_review
    if final_class in ["spam", "fyi", "needs_human_review"] and has_draft_reply:
        notes.append(f"Policy violation: Draft reply prohibited for category '{final_class}'.")
        return {
            "policy_valid": False,
            "final_classification": final_class,
            "allow_draft": False,
            "notes": notes
        }

    # Rule 3: Must draft for urgent and needs_reply
    if final_class in ["urgent", "needs_reply"] and not has_draft_reply:
        notes.append(f"Policy violation: Draft reply required for category '{final_class}'.")
        return {
            "policy_valid": False,
            "final_classification": final_class,
            "allow_draft": True,
            "notes": notes
        }

    return {
        "policy_valid": True,
        "final_classification": final_class,
        "allow_draft": final_class in ["urgent", "needs_reply"],
        "notes": notes
    }
