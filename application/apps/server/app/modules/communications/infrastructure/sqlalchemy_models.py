"""Current SQLite schema for COM-001."""

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.sqlalchemy_models import LocalBase


class CommunicationModel(LocalBase):
    __tablename__ = "communications"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    direction: Mapped[str] = mapped_column(String, nullable=False)
    channel: Mapped[str] = mapped_column(String, nullable=False)
    subject: Mapped[str] = mapped_column(String, nullable=False)
    body: Mapped[str] = mapped_column(String, nullable=False)
    occurred_at_utc: Mapped[str] = mapped_column(String, nullable=False)
    occurred_timezone: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    recorded_at: Mapped[str | None] = mapped_column(String)
    supersedes_communication_id: Mapped[str | None] = mapped_column(ForeignKey("communications.id"), unique=True)
    superseded_by_communication_id: Mapped[str | None] = mapped_column(ForeignKey("communications.id"), unique=True)
    correction_reason: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
    __table_args__ = (
        CheckConstraint("direction IN ('inbound','outbound','internal')"),
        CheckConstraint("channel IN ('phone','email','sms','in_person','letter','other')"),
        CheckConstraint("status IN ('draft','recorded','superseded')"),
        CheckConstraint("length(trim(subject)) BETWEEN 1 AND 240"),
        CheckConstraint("length(trim(body)) BETWEEN 1 AND 10000"),
        CheckConstraint("length(trim(occurred_timezone)) > 0"),
        CheckConstraint("(status = 'draft' AND recorded_at IS NULL AND supersedes_communication_id IS NULL AND superseded_by_communication_id IS NULL AND correction_reason IS NULL) OR (status = 'recorded' AND recorded_at IS NOT NULL AND superseded_by_communication_id IS NULL AND ((supersedes_communication_id IS NULL AND correction_reason IS NULL) OR (supersedes_communication_id IS NOT NULL AND correction_reason IS NOT NULL AND length(trim(correction_reason)) BETWEEN 1 AND 1000))) OR (status = 'superseded' AND recorded_at IS NOT NULL AND supersedes_communication_id IS NULL AND superseded_by_communication_id IS NOT NULL AND correction_reason IS NULL)"),
        Index("communications_occurred", "occurred_at_utc", "id"),
        Index("communications_status_occurred", "status", "occurred_at_utc", "id"),
    )


class CommunicationParticipantModel(LocalBase):
    __tablename__ = "communication_participants"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    communication_id: Mapped[str] = mapped_column(ForeignKey("communications.id"), nullable=False)
    party_id: Mapped[str] = mapped_column(ForeignKey("parties.id"), nullable=False)
    party_contact_method_id: Mapped[str | None] = mapped_column(ForeignKey("party_contact_methods.id"))
    role: Mapped[str] = mapped_column(String, nullable=False)
    party_display_name_snapshot: Mapped[str] = mapped_column(String, nullable=False)
    contact_display_snapshot: Mapped[str | None] = mapped_column(String)
    __table_args__ = (
        CheckConstraint("role IN ('sender','recipient','reporter','other')"),
        CheckConstraint("length(trim(party_display_name_snapshot)) > 0"),
        Index("communication_participants_communication", "communication_id", "id"),
        Index("communication_participants_party", "party_id", "communication_id"),
    )


class CommunicationLinkModel(LocalBase):
    __tablename__ = "communication_links"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    communication_id: Mapped[str] = mapped_column(ForeignKey("communications.id"), nullable=False)
    entity_type: Mapped[str] = mapped_column(String, nullable=False)
    entity_id: Mapped[str] = mapped_column(String, nullable=False)
    property_timezone_snapshot: Mapped[str | None] = mapped_column(String)
    __table_args__ = (
        CheckConstraint("entity_type IN ('party','property','space','lease','rent_expectation','rent_receipt','renewal_option','task','maintenance_issue','owner_concern')"),
        UniqueConstraint("communication_id", "entity_type", "entity_id", name="communication_links_unique_target"),
        Index("communication_links_target", "entity_type", "entity_id", "communication_id"),
    )


class CommunicationOperationModel(LocalBase):
    __tablename__ = "communication_operations"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    target_communication_id: Mapped[str | None] = mapped_column(ForeignKey("communications.id"))
    result_communication_id: Mapped[str | None] = mapped_column(ForeignKey("communications.id"))
    action: Mapped[str] = mapped_column(String, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    correlation_id: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    follow_up_task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"))
    __table_args__ = (
        CheckConstraint("action IN ('created','recorded','corrected','patched')"),
        CheckConstraint("length(request_fingerprint) = 64"),
        Index("communication_operations_result", "result_communication_id"),
    )
