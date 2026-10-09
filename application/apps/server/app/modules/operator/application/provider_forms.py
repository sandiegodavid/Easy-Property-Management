"""Slice 36 bounded, incomplete Provider and category recovery forms."""

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import Field, StrictBool, StrictInt

from app.modules.operator.application.identity_forms import ContactFields
from app.modules.operator.domain.models import Contract


class ProviderForm(Contract):
    expectedRevision: StrictInt | None = Field(None, ge=1)


class ProfileFields(Contract):
    selectionStatus: Literal["neutral", "preferred", "avoid"] | None = None
    selectionReason: str | None = Field(None, max_length=1000)
    notes: str | None = Field(None, max_length=4000)


class ProfilePatchForm(ProfileFields, ProviderForm):
    pass


class DesignateForm(ProfileFields):
    expectedRevision: StrictInt | None = Field(None, ge=0, le=0)


class PartyFields(Contract):
    partyKind: Literal["individual", "organization"] | None = None
    displayName: str | None = Field(None, max_length=240)


class ServiceFields(Contract):
    displayName: str | None = Field(None, max_length=160)


class AreaFields(ServiceFields):
    countryCode: str | None = Field(None, min_length=2, max_length=2)


class WorkFields(Contract):
    performedOn: date | None = None
    summary: str | None = Field(None, max_length=1000)
    propertyId: UUID | None = None
    outcomeNotes: str | None = Field(None, max_length=4000)


class ReferenceFields(Contract):
    referenceName: str | None = Field(None, max_length=240)
    organizationName: str | None = Field(None, max_length=240)
    relationship: str | None = Field(None, max_length=240)
    email: str | None = Field(None, max_length=320)
    phone: str | None = Field(None, max_length=320)
    notes: str | None = Field(None, max_length=4000)


class ReputationFields(Contract):
    sourceKind: Literal["google", "yelp", "angi", "other"] | None = None
    sourceName: str | None = Field(None, max_length=80)
    url: str | None = Field(None, max_length=2048)
    notes: str | None = Field(None, max_length=4000)
    lastCheckedOn: date | None = None


class CreateForm(DesignateForm):
    party: PartyFields | None = None
    contacts: list[ContactFields] | None = Field(None, max_length=100)
    services: list[ServiceFields] | None = Field(None, max_length=100)
    serviceAreas: list[AreaFields] | None = Field(None, max_length=100)
    workHistory: list[WorkFields] | None = Field(None, max_length=100)
    references: list[ReferenceFields] | None = Field(None, max_length=100)
    categoryIds: list[UUID] | None = Field(None, max_length=100)
    confirmedNewParty: StrictBool | None = None


class ServiceForm(ServiceFields, ProviderForm):
    itemId: UUID | None = None


class AreaForm(AreaFields, ProviderForm):
    itemId: UUID | None = None


class WorkForm(WorkFields, ProviderForm):
    itemId: UUID | None = None


class ReferenceForm(ReferenceFields, ProviderForm):
    itemId: UUID | None = None


class ReputationForm(ReputationFields, ProviderForm):
    itemId: UUID | None = None


class ArchiveForm(ProviderForm):
    confirmed: StrictBool | None = None


class ChildArchiveForm(ArchiveForm):
    itemId: UUID | None = None


class ChildRestoreForm(ProviderForm):
    itemId: UUID | None = None


class CategoryFields(Contract):
    displayName: str | None = Field(None, max_length=160)
    description: str | None = Field(None, max_length=1000)
    displayOrder: StrictInt | None = Field(None, ge=0)


class CategoryCreateForm(CategoryFields):
    expectedRevision: StrictInt | None = Field(None, ge=0, le=0)


class CategoryPatchForm(CategoryFields, ProviderForm):
    pass


class CategoryArchiveForm(ArchiveForm):
    reason: str | None = Field(None, max_length=1000)


class AssignmentForm(ProviderForm):
    categoryId: UUID | None = None
    expectedCategoryRevision: StrictInt | None = Field(None, ge=1)


class AssignmentArchiveForm(CategoryArchiveForm):
    assignmentId: UUID | None = None


class AssignmentRestoreForm(ArchiveForm):
    assignmentId: UUID | None = None
    expectedCategoryRevision: StrictInt | None = Field(None, ge=1)


PROVIDER_SCHEMAS = {
    "provider.create": CreateForm,
    "provider.designate": DesignateForm,
    "provider.profile.patch": ProfilePatchForm,
    "provider.archive": ArchiveForm,
    "provider.restore": ProviderForm,
    "provider.category.create": CategoryCreateForm,
    "provider.category.patch": CategoryPatchForm,
    "provider.category.archive": CategoryArchiveForm,
    "provider.category.restore": ArchiveForm,
    "provider.category_assignment.assign": AssignmentForm,
    "provider.category_assignment.archive": AssignmentArchiveForm,
    "provider.category_assignment.restore": AssignmentRestoreForm,
    **{
        f"provider.{kind}.{verb}": schema
        for kind, fields in (
            ("service", ServiceForm),
            ("area", AreaForm),
            ("work_history", WorkForm),
            ("reference", ReferenceForm),
            ("reputation_link", ReputationForm),
        )
        for verb, schema in (
            ("add", fields),
            ("update", fields),
            ("archive", ChildArchiveForm),
            ("restore", ChildRestoreForm),
        )
    },
}


def provider_source_kind(form):
    if form in {"provider.create", "provider.category.create"}:
        return None
    return "provider_category" if form.startswith("provider.category.") else "provider"
