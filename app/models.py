from typing import Optional
from sqlmodel import SQLModel, Field
from datetime import datetime

class Vehicle(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    call_sign: str
    type: str
    status: str = "S2"
    color: Optional[str] = None
    notes: Optional[str] = None

class Incident(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    number: str
    priority: int = 2
    keyword: str
    subtitle: Optional[str] = None
    address_json: str
    details: Optional[str] = None
    status: str = "DRAFT"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    activated_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None

class LogEntry(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    incident_id: int
    time: datetime = Field(default_factory=datetime.utcnow)
    category: str = "NOTE"
    text: str
    by: Optional[str] = None
    related_vehicle_id: Optional[int] = None
