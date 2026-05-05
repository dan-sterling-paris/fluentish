from datetime import datetime
from pydantic import BaseModel
from app.models import LeadStatus


class MessageOut(BaseModel):
    id: int
    lead_id: int
    direction: str
    body: str
    sent_at: datetime

    model_config = {"from_attributes": True}


class LeadOut(BaseModel):
    id: int
    name: str
    phone: str
    status: LeadStatus
    created_at: datetime
    updated_at: datetime
    last_message_at: datetime | None = None

    model_config = {"from_attributes": True}


class LeadWithMessages(LeadOut):
    messages: list[MessageOut] = []


class SendMessageIn(BaseModel):
    body: str
