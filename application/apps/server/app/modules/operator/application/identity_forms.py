"""Approved bounded Party and Tenant incomplete command forms."""

from typing import Literal
from uuid import UUID

from pydantic import Field, StrictBool, StrictInt, model_validator

from app.modules.operator.domain.models import Contract


class IdentityForm(Contract):
    expectedRevision: StrictInt | None = Field(None, ge=1)


class ContactFields(Contract):
    methodKind: Literal["email", "phone"] | None = None
    value: str | None = Field(None, max_length=320)
    extension: str | None = Field(None, max_length=6)
    label: str | None = Field(None, max_length=80)


class PartyCreateForm(Contract):
    expectedRevision: StrictInt | None = Field(None, ge=0, le=0)
    partyKind: Literal["individual", "organization"] | None = None
    displayName: str | None = Field(None, max_length=240)
    contacts: list[ContactFields] | None = Field(None, max_length=100)
    confirmedNewParty: StrictBool | None = None


class PartyPatchForm(IdentityForm):
    displayName: str | None = Field(None, max_length=240)


class ArchiveForm(IdentityForm):
    confirmed: StrictBool | None = None


class ContactAddForm(ContactFields, IdentityForm):
    pass


class ContactUpdateForm(ContactAddForm):
    methodId: UUID | None = None


class ReferenceResolution(Contract):
    role: str = Field(min_length=1, max_length=100)
    roleRecordId: UUID
    replacementContactMethodId: UUID | None = None
    clear: StrictBool = False
    expectedTenantRevision: StrictInt | None = Field(None, ge=1)

    @model_validator(mode="after")
    def exact_resolution(self):
        if (self.role == "tenant") != (self.expectedTenantRevision is not None):
            raise ValueError("Only Tenant resolutions require expectedTenantRevision.")
        if (self.replacementContactMethodId is None) == (self.clear is False):
            raise ValueError("Choose a replacement or explicit clear, not both.")
        return self


class ContactArchiveForm(ArchiveForm):
    methodId: UUID | None = None
    referenceResolutions: list[ReferenceResolution] | None = Field(None, max_length=20)


class ContactRestoreForm(IdentityForm):
    methodId: UUID | None = None


class TenantCreateForm(PartyCreateForm):
    notes: str | None = Field(None, max_length=4000)
    doNotContact: StrictBool | None = None


class TenantDesignateForm(Contract):
    expectedRevision: StrictInt | None = Field(None, ge=0, le=0)
    notes: str | None = Field(None, max_length=4000)


class TenantPatchForm(IdentityForm):
    preferredContactMethodId: UUID | None = None
    doNotContact: StrictBool | None = None
    notes: str | None = Field(None, max_length=4000)


IDENTITY_SCHEMAS = {
    "party.create": PartyCreateForm,
    "party.patch": PartyPatchForm,
    "party.archive": ArchiveForm,
    "party.restore": IdentityForm,
    "party.contact.add": ContactAddForm,
    "party.contact.update": ContactUpdateForm,
    "party.contact.archive": ContactArchiveForm,
    "party.contact.restore": ContactRestoreForm,
    "tenant.create": TenantCreateForm,
    "tenant.designate": TenantDesignateForm,
    "tenant.profile.patch": TenantPatchForm,
    "tenant.archive": ArchiveForm,
    "tenant.restore": IdentityForm,
}


def identity_source_kind(form):
    if form in {"party.create", "tenant.create"}:
        return None
    return "party" if form.startswith("party.") else "tenant"
