from pydantic import BaseModel
from enum import Enum
from typing import Optional
from datetime import datetime


class CallStatus(str, Enum):
    PENDING = "pending"
    DIALING = "dialing"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    NO_ANSWER = "no_answer"


class CallCreate(BaseModel):
    phone: str
    task: str
    language: str = "auto"
    caller_name: Optional[str] = None
    required_info: Optional[str] = None
    restrictions: Optional[str] = None


class CallResponse(BaseModel):
    id: str
    phone: str
    task: str
    language: str
    status: CallStatus
    transcript: Optional[str] = None
    report: Optional[str] = None
    created_at: str
    completed_at: Optional[str] = None
    duration_seconds: Optional[int] = None


class CallUpdate(BaseModel):
    status: Optional[CallStatus] = None
    transcript: Optional[str] = None
    report: Optional[str] = None
    completed_at: Optional[str] = None
    duration_seconds: Optional[int] = None
