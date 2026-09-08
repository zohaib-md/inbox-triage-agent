from typing import Optional
from pydantic import BaseModel, Field


class FlightStatusInfo(BaseModel):
    flight_number: str = Field(..., description="Flight code, e.g. 6E 204 or AI 432")
    airline: Optional[str] = Field(None, description="Airline name")
    origin: Optional[str] = Field(None, description="Origin airport or city")
    destination: Optional[str] = Field(None, description="Destination airport or city")
    status: str = Field("Scheduled", description="On Time, Delayed, Landed, Departed, Cancelled")
    delay_minutes: Optional[int] = Field(0, description="Delay in minutes if any")
    scheduled_departure: Optional[str] = Field(None, description="Departure time e.g. 14:30")
    estimated_departure: Optional[str] = Field(None, description="Estimated departure time")
    scheduled_arrival: Optional[str] = Field(None, description="Arrival time e.g. 16:00")
    estimated_arrival: Optional[str] = Field(None, description="Estimated arrival time")
    terminal: Optional[str] = Field(None, description="Departure or arrival terminal")
    gate: Optional[str] = Field(None, description="Boarding gate")
    summary: Optional[str] = Field(None, description="Summary details")


class TrainStatusInfo(BaseModel):
    train_number: str = Field(..., description="Train number or name e.g. 12004 or Lucknow Shatabdi")
    train_name: Optional[str] = Field(None, description="Train official name")
    origin: Optional[str] = Field(None, description="Origin station")
    destination: Optional[str] = Field(None, description="Destination station")
    status: str = Field("Running on Time", description="Live running status")
    delay_minutes: Optional[int] = Field(0, description="Delay in minutes")
    current_location: Optional[str] = Field(None, description="Last station crossed or current location")
    next_station: Optional[str] = Field(None, description="Next upcoming station")
    platform: Optional[str] = Field(None, description="Expected platform number")
    scheduled_departure: Optional[str] = Field(None, description="Departure time")
    scheduled_arrival: Optional[str] = Field(None, description="Arrival time")
    summary: Optional[str] = Field(None, description="Key running details")


class PNRInfo(BaseModel):
    pnr_number: str = Field(..., description="10-digit PNR number")
    train_number: Optional[str] = Field(None, description="Associated train number if found")
    train_name: Optional[str] = Field(None, description="Associated train name if found")
    journey_date: Optional[str] = Field(None, description="Date of journey if found")
    coach: Optional[str] = Field(None, description="Coach number (e.g. B2, M1, C1)")
    berth_seat: Optional[str] = Field(None, description="Berth or seat number")
    status: Optional[str] = Field(None, description="Booking status e.g. CNF, RAC, WL")
    direct_check_url: str = Field(..., description="Direct link to check live IRCTC/ConfirmTkt status")
