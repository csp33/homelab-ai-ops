"""Domain models for agent memory and feedback."""

from datetime import datetime

from pydantic import BaseModel, Field


class MemoryEntry(BaseModel):
    """A persisted memory item representing operator feedback or an incident lesson."""

    id: int | None = Field(default=None, description="Unique memory ID in PostgreSQL")
    namespace: str = Field(..., description="Target Kubernetes namespace")
    service_name: str = Field(..., description="Target service or deployment name")
    alert_name: str | None = Field(default=None, description="Alert name if triggered by an alert")
    incident_pattern: str = Field(
        ..., description="Description or pattern of the incident / observed symptoms"
    )
    operator_feedback: str = Field(
        ..., description="Human operator feedback or instructions for this situation"
    )
    action_rule: str | None = Field(
        default=None,
        description="Explicit rule or remediation recommendation given by operator",
    )
    created_at: datetime | None = Field(
        default=None, description="Timestamp when memory was recorded"
    )


class FeedbackRequest(BaseModel):
    """Payload to register new human feedback / lesson learned."""

    namespace: str = Field(..., description="Kubernetes namespace")
    service_name: str = Field(..., description="Service or deployment name")
    alert_name: str | None = Field(default=None, description="Optional alert name")
    incident_pattern: str = Field(
        ..., description="Context, error symptoms, or incident description"
    )
    operator_feedback: str = Field(
        ..., description="Correction, feedback, or rule provided by operator"
    )
    action_rule: str | None = Field(
        default=None,
        description="Specific recommended action (e.g., 'Do not bump RAM; truncate logs table first')",
    )


class MemoryQueryResult(BaseModel):
    """A memory entry retrieved via similarity search with its relevance score."""

    memory: MemoryEntry
    similarity: float = Field(
        ..., description="Cosine similarity score (0.0 to 1.0, higher is more similar)"
    )
