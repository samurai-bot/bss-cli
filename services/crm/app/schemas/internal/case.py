"""Internal Case + CaseNote DTOs (snake_case)."""

from datetime import datetime

from pydantic import BaseModel


class CaseResponse(BaseModel):
    id: str
    customer_id: str
    subject: str
    description: str | None = None
    state: str
    priority: str | None = None
    category: str | None = None
    resolution_code: str | None = None
    opened_by_agent_id: str | None = None
    opened_at: datetime
    closed_at: datetime | None = None
    notes: list["CaseNoteResponse"] = []
    ticket_ids: list[str] = []


class CaseNoteResponse(BaseModel):
    id: str
    case_id: str
    author_agent_id: str | None = None
    body: str
    created_at: datetime


class OpenCaseRequest(BaseModel):
    customer_id: str
    subject: str
    description: str | None = None
    priority: str = "normal"
    category: str = "general"
    opened_by_agent_id: str | None = None


class UpdateCaseRequest(BaseModel):
    priority: str | None = None
    category: str | None = None


class CloseCaseRequest(BaseModel):
    resolution_code: str


class TransitionCaseRequest(BaseModel):
    trigger: str
    resolution_code: str | None = None


class AddNoteRequest(BaseModel):
    body: str
    author_agent_id: str | None = None


def to_case_response(c) -> CaseResponse:
    return CaseResponse(
        id=c.id,
        customer_id=c.customer_id,
        subject=c.subject,
        description=c.description,
        state=c.state,
        priority=c.priority,
        category=c.category,
        resolution_code=c.resolution_code,
        opened_by_agent_id=c.opened_by_agent_id,
        opened_at=c.opened_at,
        closed_at=c.closed_at,
        notes=[
            CaseNoteResponse(
                id=n.id,
                case_id=n.case_id,
                author_agent_id=n.author_agent_id,
                body=n.body,
                created_at=n.created_at,
            )
            for n in (c.notes or [])
        ],
        ticket_ids=[t.id for t in (c.tickets or [])],
    )


def to_case_note_response(n) -> CaseNoteResponse:
    return CaseNoteResponse(
        id=n.id,
        case_id=n.case_id,
        author_agent_id=n.author_agent_id,
        body=n.body,
        created_at=n.created_at,
    )
