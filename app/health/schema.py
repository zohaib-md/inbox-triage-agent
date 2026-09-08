from typing import Literal, Optional
from pydantic import BaseModel, Field


class MedicationSchedule(BaseModel):
    name: str = Field(description="Name of the medicine or supplement (e.g. 'Amoxicillin', 'Vitamin D3').")
    dosage: str = Field(default="1 dose", description="Dosage amount (e.g. '500mg', '1 tablet', '1000 IU').")
    times: list[str] = Field(description="List of daily times in 24-hour HH:MM format (e.g. ['09:00', '21:00']).")
    instructions: Optional[str] = Field(default=None, description="Special instructions (e.g. 'after breakfast', 'with water', 'before bed').")
    duration_days: Optional[int] = Field(default=None, description="Number of days to take this medication (e.g. 7). None for ongoing.")
    start_date: str = Field(description="Start date in YYYY-MM-DD format.")


class MedicationLogEntry(BaseModel):
    id: str = Field(description="Unique identifier for log entry.")
    med_name: str = Field(description="Name of the medication.")
    dosage: str = Field(description="Dosage taken.")
    scheduled_time: str = Field(description="Scheduled time (e.g. '09:00').")
    taken_time: str = Field(description="Actual timestamp when taken in ISO format.")
    status: Literal["taken", "snoozed", "missed"] = Field(default="taken", description="Status of the dose.")


class MedicationExtractionResult(BaseModel):
    medications: list[MedicationSchedule] = Field(
        default_factory=list,
        description="Extracted medication schedules from the user voice or text."
    )
    confirmation_message: str = Field(
        description="Friendly conversational confirmation message with emojis formatted for Telegram."
    )
