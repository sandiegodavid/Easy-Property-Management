from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from app.platform.sqlalchemy_models import LocalBase

class ConditionReportModel(LocalBase):
    __tablename__ = "condition_reports"
    id: Mapped[str] = mapped_column(String, primary_key=True); lease_id: Mapped[str] = mapped_column(String, ForeignKey("leases.id"), nullable=False); space_id: Mapped[str] = mapped_column(String, ForeignKey("spaces.id"), nullable=False)
    report_kind: Mapped[str] = mapped_column(String, nullable=False); status: Mapped[str] = mapped_column(String, nullable=False); walkthrough_on: Mapped[str] = mapped_column(String, nullable=False); conducted_by: Mapped[str] = mapped_column(String, nullable=False); tenant_presence: Mapped[str] = mapped_column(String, nullable=False)
    supersedes_report_id: Mapped[str|None] = mapped_column(String, ForeignKey("condition_reports.id")); correction_reason: Mapped[str|None] = mapped_column(String); timing_exception_reason: Mapped[str|None] = mapped_column(String); general_notes: Mapped[str|None] = mapped_column(String); finalized_at: Mapped[str|None] = mapped_column(String); created_at: Mapped[str] = mapped_column(String, nullable=False); updated_at: Mapped[str] = mapped_column(String, nullable=False)
    __table_args__=(CheckConstraint("report_kind IN ('pre_move_in','post_move_out')"),CheckConstraint("status IN ('draft','finalized','superseded')"),CheckConstraint("tenant_presence IN ('present','not_present','declined','not_recorded')"),CheckConstraint("(supersedes_report_id IS NULL AND correction_reason IS NULL) OR (supersedes_report_id IS NOT NULL AND length(trim(correction_reason)) > 0)"),Index("condition_reports_lease_kind_status","lease_id","report_kind","status"),Index("condition_reports_one_current_finalized","lease_id","report_kind",unique=True,sqlite_where=(status == "finalized")))

class ConditionAreaModel(LocalBase):
    __tablename__="condition_areas"; id:Mapped[str]=mapped_column(String,primary_key=True); condition_report_id:Mapped[str]=mapped_column(String,ForeignKey("condition_reports.id"),nullable=False); display_name:Mapped[str]=mapped_column(String,nullable=False); normalized_name:Mapped[str]=mapped_column(String,nullable=False); sort_order:Mapped[int]=mapped_column(Integer,nullable=False); notes:Mapped[str|None]=mapped_column(String)
    __table_args__=(CheckConstraint("sort_order >= 0"),Index("condition_areas_report_name","condition_report_id","normalized_name",unique=True))

class ConditionObservationModel(LocalBase):
    __tablename__="condition_observations"; id:Mapped[str]=mapped_column(String,primary_key=True); condition_area_id:Mapped[str]=mapped_column(String,ForeignKey("condition_areas.id"),nullable=False); item_name:Mapped[str]=mapped_column(String,nullable=False); normalized_name:Mapped[str]=mapped_column(String,nullable=False); condition_state:Mapped[str]=mapped_column(String,nullable=False); cleanliness_state:Mapped[str|None]=mapped_column(String); observed_on:Mapped[str]=mapped_column(String,nullable=False); is_completed:Mapped[bool]=mapped_column(Boolean,nullable=False); completed_at:Mapped[str|None]=mapped_column(String); notes:Mapped[str|None]=mapped_column(String); sort_order:Mapped[int]=mapped_column(Integer,nullable=False)
    __table_args__=(CheckConstraint("condition_state IN ('good','fair','poor','damaged','missing','not_tested','not_applicable')"),CheckConstraint("cleanliness_state IS NULL OR cleanliness_state IN ('clean','needs_cleaning','not_assessed')"),CheckConstraint("sort_order >= 0"),CheckConstraint("(is_completed = 1 AND completed_at IS NOT NULL) OR (is_completed = 0 AND completed_at IS NULL)"),Index("condition_observations_area_name","condition_area_id","normalized_name",unique=True))

class ConditionAcknowledgmentModel(LocalBase):
    __tablename__="condition_report_acknowledgments"; id:Mapped[str]=mapped_column(String,primary_key=True); condition_report_id:Mapped[str]=mapped_column(String, ForeignKey("condition_reports.id"),nullable=False); lease_participant_id:Mapped[str]=mapped_column(String, ForeignKey("lease_participants.id"),nullable=False); status:Mapped[str]=mapped_column(String,nullable=False); acknowledged_on:Mapped[str|None]=mapped_column(String); notes:Mapped[str|None]=mapped_column(String)
    __table_args__=(CheckConstraint("status IN ('acknowledged','disputed','declined','not_requested','pending')"),Index("condition_ack_report_participant","condition_report_id","lease_participant_id",unique=True))

class ConditionComparisonModel(LocalBase):
    __tablename__="condition_comparisons"; id:Mapped[str]=mapped_column(String,primary_key=True); lease_id:Mapped[str]=mapped_column(String, ForeignKey("leases.id"),nullable=False); pre_report_id:Mapped[str]=mapped_column(String, ForeignKey("condition_reports.id"),nullable=False); post_report_id:Mapped[str]=mapped_column(String, ForeignKey("condition_reports.id"),nullable=False); pre_observation_id:Mapped[str|None]=mapped_column(String, ForeignKey("condition_observations.id")); post_observation_id:Mapped[str|None]=mapped_column(String, ForeignKey("condition_observations.id")); comparison_state:Mapped[str]=mapped_column(String,nullable=False); operator_notes:Mapped[str|None]=mapped_column(String); created_at:Mapped[str]=mapped_column(String,nullable=False); updated_at:Mapped[str]=mapped_column(String,nullable=False)
    __table_args__=(CheckConstraint("comparison_state IN ('unchanged','improved','normal_wear','possible_tenant_damage','maintenance_needed','not_comparable')"),CheckConstraint("pre_observation_id IS NOT NULL OR post_observation_id IS NOT NULL"),CheckConstraint("comparison_state NOT IN ('possible_tenant_damage','not_comparable') OR length(trim(operator_notes)) > 0"),Index("condition_comparisons_lease","lease_id"),Index("condition_comparisons_pre_once_per_pair","pre_report_id","post_report_id","pre_observation_id",unique=True,sqlite_where=pre_observation_id.is_not(None)),Index("condition_comparisons_post_once_per_pair","pre_report_id","post_report_id","post_observation_id",unique=True,sqlite_where=post_observation_id.is_not(None)))


class ConditionChecklistTemplateModel(LocalBase):
    __tablename__ = "condition_checklist_templates"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    normalized_name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    applicability: Mapped[str] = mapped_column(String, nullable=False)
    notes: Mapped[str | None] = mapped_column(String)
    archived_at: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
    __table_args__ = (CheckConstraint("applicability IN ('residential','office','any')"),)


class ConditionChecklistTemplateItemModel(LocalBase):
    __tablename__ = "condition_checklist_template_items"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    template_id: Mapped[str] = mapped_column(String, ForeignKey("condition_checklist_templates.id"), nullable=False)
    area_display_name: Mapped[str] = mapped_column(String, nullable=False)
    area_normalized_name: Mapped[str] = mapped_column(String, nullable=False)
    item_name: Mapped[str] = mapped_column(String, nullable=False)
    item_normalized_name: Mapped[str] = mapped_column(String, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    __table_args__ = (
        CheckConstraint("sort_order >= 0"),
        Index("condition_template_item_name", "template_id", "area_normalized_name", "item_normalized_name", unique=True),
    )
