import json
import re

def parse_agent_response(instance):
    """Extracts JSON payload from response text or candidate."""
    # Handle single-turn response candidate
    responses = instance.get("responses") or []
    if responses and isinstance(responses, list):
        first_resp = responses[0]
        if isinstance(first_resp, dict) and "response" in first_resp:
            parts = first_resp["response"].get("parts", [])
            if parts and isinstance(parts[0], dict) and "text" in parts[0]:
                raw_text = parts[0]["text"]
            else:
                raw_text = str(first_resp)
        else:
            raw_text = str(first_resp)
    elif "agent_data" in instance:
        turns = (instance.get("agent_data") or {}).get("turns", [])
        raw_text = ""
        for turn in turns:
            for event in turn.get("events", []):
                if event.get("author") != "user":
                    content = event.get("content", {})
                    parts = content.get("parts", [])
                    for part in parts:
                        if isinstance(part, dict) and "text" in part:
                            raw_text += part["text"] + "\n"
    else:
        raw_text = str(instance)

    # Try to parse JSON from Markdown code blocks or directly
    json_match = re.search(r"```json\s*(.*?)\s*```", raw_text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except Exception:
            pass
    try:
        return json.loads(raw_text)
    except Exception:
        # Fuzzy extraction
        class_match = re.search(r'"classification":\s*"([^"]+)"', raw_text)
        draft_match = re.search(r'"draft_reply":\s*(".*?"|null)', raw_text, re.DOTALL)
        return {
            "classification": class_match.group(1) if class_match else "unknown",
            "draft_reply": json.loads(draft_match.group(1)) if draft_match else None,
            "raw": raw_text
        }

def evaluate_classification(instance):
    """Checks if the predicted classification matches expected."""
    parsed = parse_agent_response(instance)
    expected = instance.get("expected_classification")
    predicted = parsed.get("classification")
    
    passed = (predicted == expected)
    return {
        "score": 1.0 if passed else 0.0,
        "predicted": predicted,
        "expected": expected,
        "passed": passed,
        "reason": f"Predicted '{predicted}', expected '{expected}'"
    }

def evaluate_draft_safety(instance):
    """Ensures spam, fyi, and needs_human_review do NOT get drafts."""
    parsed = parse_agent_response(instance)
    classification = parsed.get("classification")
    draft = parsed.get("draft_reply")

    if classification in ["spam", "fyi", "needs_human_review"]:
        # Must NOT have a draft
        safe = (draft is None or draft == "" or draft == "null")
        return {
            "score": 1.0 if safe else 0.0,
            "passed": safe,
            "reason": f"Category '{classification}' correctly has no draft" if safe else f"VIOLATION: Category '{classification}' drafted a reply: {str(draft)[:60]}"
        }
    elif classification in ["urgent", "needs_reply"]:
        # Must have a non-empty draft
        has_draft = bool(draft and len(str(draft).strip()) > 20)
        return {
            "score": 1.0 if has_draft else 0.0,
            "passed": has_draft,
            "reason": f"Category '{classification}' has drafted reply ({len(str(draft or ''))} chars)" if has_draft else f"MISSING DRAFT: Category '{classification}' requires a suggested reply draft"
        }
    return {"score": 0.0, "passed": False, "reason": f"Unrecognized category: {classification}"}
