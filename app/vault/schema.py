import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field


class VaultDocument(BaseModel):
    doc_id: str = Field(..., description="Unique document ID")
    filename: str = Field(..., description="Original filename")
    mime_type: str = Field("application/pdf", description="MIME type")
    doc_type: str = Field("General Document", description="Category: Medical, Insurance, Contract/Legal, Finance, Identity, Other")
    upload_date: str = Field(default_factory=lambda: datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
    extracted_summary: str = Field(..., description="Concise multi-line summary of the document")
    key_entities: list[str] = Field(default_factory=list, description="Key metrics, policy numbers, dates, test results")
    file_path: Optional[str] = Field(None, description="Local storage file path")


class VaultQueryResult(BaseModel):
    question: str = Field(..., description="User's query")
    answer: str = Field(..., description="Synthesized answer based on the document")
    referenced_documents: list[str] = Field(default_factory=list, description="Documents used for answer")
    formatted_reply: str = Field(..., description="Telegram formatted markdown reply")
