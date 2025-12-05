from typing import List, Optional, Literal
from datetime import datetime
from beanie import Document
from pydantic import BaseModel, Field


class CourseEnrollment(BaseModel):
    course_id: str
    approval_status: Literal["pending", "approved", "rejected"] = "pending"
    payment_method: Literal["sham", "haram"]
    payment_receipt: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Notification(BaseModel):
    student_id: int
    type: str
    message: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class User(Document):
    telegram_id: int
    full_name: str
    phone: str
    email: str
    study_year: Optional[int] = None
    specialization: Optional[str] = None
    registered_at: datetime = Field(default_factory=datetime.utcnow)
    last_active: datetime = Field(default_factory=datetime.utcnow)
    courses: List[CourseEnrollment] = Field(default_factory=list)
    notifications: List[Notification] = Field(default_factory=list)

    class Settings:
        name = "users"
