# inbox-triage-agent

Inbox triage agent built with Google ADK + `agents-cli` — classifies emails and drafts replies, no auto-send.

> **Status: Evaluation complete (10/10 test cases passing)**

## Overview
Automated support inbox triage system for a SaaS product. Takes inbound emails (`subject`, `sender`, `body`), classifies them, and prepares high-quality suggested reply drafts for human review.

### Core Policies
- **Categories**:
  - `urgent`: Active production outages, widespread 500 errors, customer SLA breach risks.
  - `needs_reply`: Actionable support requests (billing questions, reproducible bug reports, feature requests).
  - `fyi`: Automated system/maintenance notices with no response needed.
  - `spam`: Phishing/credential harvesting attempts and unsolicited sales pitches.
  - `needs_human_review`: Ambiguous context (e.g. unrecorded event references) or vague one-liners lacking diagnostic details.
- **Safety Guardrail**: Strictly **NO** automatic sending. Output is for human review only.
- **Draft Reply Rule**: Suggested replies are drafted **only** for `urgent` and `needs_reply`. Drafts are strictly prohibited (`null`) for `spam`, `fyi`, and `needs_human_review`.

---

## Setup

```bash
# 1. Clone the repository
git clone https://github.com/zohaib-md/inbox-triage-agent.git
cd inbox-triage-agent

# 2. Set up virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install google-agents-cli google-adk pydantic
```

---

## Evaluation & Testing

The evaluation suite tests 10 diverse cases including deliberately hard edge cases:

1. **Urgent Outage**: 500 errors on US-East API endpoints -> `urgent` (incident response draft generated)
2. **Phishing Scam**: Wallet recovery seed phrase request -> `spam` (`draft_reply: null`)
3. **Ambiguous Context**: Vague reference to SaaStr booth conversation -> `needs_human_review` (`draft_reply: null`)
4. **Routine Billing**: Switching from monthly to annual & adding VAT ID -> `needs_reply` (specific proration & tax settings draft)
5. **Vague One-Liner**: *"error / it broke again"* -> `needs_human_review` (`draft_reply: null`)
6. **FYI Notice**: Automated DB staging maintenance completion -> `fyi` (`draft_reply: null`)
7. **Reproducible Bug**: HTTP 413 Payload Too Large on 5k row CSV exports -> `needs_reply` (workaround & escalation draft)
8. **Feature Request**: Native Slack webhook alerts -> `needs_reply` (roadmap & workaround draft)
9. **SLA Breach Alert**: Enterprise customer webhook delivery failure -> `urgent` (30-min SLA escalation draft)
10. **Sales Spam**: Unsolicited B2B AI outbound lead-gen pitch -> `spam` (`draft_reply: null`)

### Running Evaluations
```bash
python3 tests/eval/eval_runner.py tests/eval/datasets/inbox-eval.json
```
**Evaluation Result: 10/10 Passed (100.0%)**

---

## CLI Usage

Run a single email through the triage pipeline using `agents-cli`:
```bash
agents-cli run "Email Subject: CRITICAL: Database connection pool exhausted\nSender: alerts@ops.com\nBody: Outage on production checkout service. 500 internal server errors across endpoints."
```

Example JSON Output:
```json
{
  "classification": "urgent",
  "confidence": 0.98,
  "reasoning": "Active critical production outage with 500 errors impacting API endpoints and checkout.",
  "draft_reply": "Hi Alex,\n\nThank you for reaching out, and we sincerely apologize for the disruption. Our on-call engineering and incident response teams have been immediately notified..."
}
```

---

## Deployment
*(Deployment options available via `agents-cli scaffold enhance` or `agents-cli deploy` — pending confirmation)*
