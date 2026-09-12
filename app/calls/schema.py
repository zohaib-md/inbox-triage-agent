from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class CallStatus(str, Enum):
    initiated = "initiated"
    ringing = "ringing"
    in_progress = "in_progress"
    completed = "completed"
    failed = "failed"
    busy = "busy"
    no_answer = "no_answer"


class CallTurn(BaseModel):
    speaker: str = Field(description="'ai' or 'human'")
    text: str = Field(description="Content of spoken turn")
    timestamp: str = Field(description="ISO timestamp of turn")


class CallExtractedData(BaseModel):
    title: Optional[str] = Field(default=None, description="Event or appointment title")
    start_time: Optional[str] = Field(default=None, description="ISO timestamp for start of appointment")
    end_time: Optional[str] = Field(default=None, description="ISO timestamp for end of appointment")
    location: Optional[str] = Field(default=None, description="Physical or virtual location")
    description: Optional[str] = Field(default=None, description="Notes, doctor name, reference number")
    outcome: str = Field(default="in_progress", description="Summary status of the negotiation/outcome")
    fee: Optional[str] = Field(default=None, description="Mentioned cost or consultation fee")
    requirements: Optional[str] = Field(default=None, description="Special instructions or items to bring")
    callback_needed: bool = Field(default=False, description="Whether human requested a callback")


class CallSession(BaseModel):
    session_id: str
    chat_id: Optional[int] = None
    to_number: str
    mission: str
    status: CallStatus = CallStatus.initiated
    call_sid: Optional[str] = None
    created_at: str
    duration_seconds: int = 0
    transcript: list[CallTurn] = Field(default_factory=list)
    summary: Optional[str] = None
    extracted_data: Optional[CallExtractedData] = None
    recording_url: Optional[str] = None
    mode: str = "live"  # "live" | "simulated"


class CallTurnResult(BaseModel):
    spoken_text: str = Field(description="The single sentence the AI should speak out loud")
    is_complete: bool = Field(description="True if mission is accomplished or human ends the call")
    extracted_data: Optional[CallExtractedData] = Field(default=None, description="Any structured details learned so far")


class CallDispatchResult(BaseModel):
    status: str
    session_id: str
    call_sid: Optional[str] = None
    mode: str
    message: str
