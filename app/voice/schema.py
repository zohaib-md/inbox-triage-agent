from typing import Literal, Optional
from pydantic import BaseModel, Field


class CalendarEvent(BaseModel):
    title: str = Field(description="Descriptive title of the calendar event or meeting.")
    start_time: str = Field(description="ISO 8601 formatted start datetime (e.g. '2026-09-09T17:00:00').")
    end_time: Optional[str] = Field(default=None, description="ISO 8601 formatted end datetime if duration specified, or 1 hour after start_time.")
    location: Optional[str] = Field(default=None, description="Location or meeting link if mentioned.")
    description: Optional[str] = Field(default=None, description="Additional context or notes for the calendar event.")


class TodoTask(BaseModel):
    task: str = Field(description="Clear, actionable task description.")
    due_date: Optional[str] = Field(default=None, description="Due date or deadline if mentioned (e.g. '2026-09-08' or 'Friday noon').")
    priority: Literal["low", "medium", "high"] = Field(default="medium", description="Task priority based on user urgency.")
    category: Literal["work", "personal", "errand", "urgent"] = Field(default="personal", description="Category classification.")


class VoiceExtractionResult(BaseModel):
    events: list[CalendarEvent] = Field(
        default_factory=list,
        description="List of calendar appointments, meetings, or time-specific events extracted."
    )
    tasks: list[TodoTask] = Field(
        default_factory=list,
        description="List of to-do items, reminders, or errands extracted."
    )
    confirmation_message: str = Field(
        description="Conversational Telegram markdown message with emojis confirming what was scheduled and logged."
    )
