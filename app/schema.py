from typing import Literal, Optional
from pydantic import BaseModel, Field

TriageCategory = Literal["urgent", "needs_reply", "fyi", "spam", "needs_human_review"]

class EmailInput(BaseModel):
    subject: str = Field(description="The subject line of the email.")
    sender: str = Field(description="The sender's email address.")
    body: str = Field(description="The body content of the incoming email.")

class TriageResult(BaseModel):
    classification: TriageCategory = Field(
        description="Classification category: urgent, needs_reply, fyi, spam, or needs_human_review if ambiguous or low confidence."
    )
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="Confidence score between 0.0 and 1.0 in the classification decision."
    )
    reasoning: str = Field(
        description="Brief concise rationale explaining why this classification was assigned."
    )
    draft_reply: Optional[str] = Field(
        default=None,
        description="Suggested reply draft for urgent or needs_reply. Must be null for spam, fyi, or needs_human_review."
    )
