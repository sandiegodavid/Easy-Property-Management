"""Owning ingress projection contracts; source identity/enablement remain H03/H04."""

from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import AfterValidator, Field, model_validator

from app.platform.hosted_contracts.semantic import SemanticRequest
from app.platform.hosted_contracts.values import CanonicalId, Revision, Contract

MAX_ORIGINS = 4096


def exact_origin(value):
    parsed = urlsplit(value)
    host = parsed.hostname or ""
    labels = host.split(".")
    if (
        value != "https://" + host
        or not host.isascii()
        or len(host) > 253
        or len(labels) < 3
        or any(
            not label
            or len(label) > 63
            or not label[0].isalnum()
            or not label[-1].isalnum()
            or any(not (char.isalnum() or char == "-") for char in label)
            for label in labels
        )
        or labels[0] in {"admin", "login", "api", "www"}
    ):
        raise ValueError("A canonical registered HTTPS origin is required.")
    return value


Origin = Annotated[str, AfterValidator(exact_origin)]


class IngressRecord(SemanticRequest):
    operator_id: CanonicalId
    workspace_id: CanonicalId
    binding_id: CanonicalId
    resource_generation: Revision
    public_origin: Origin
    access_epoch: Revision
    desired_state: Literal["held", "blocked", "eligible"]
    operation_id: CanonicalId


class IngressProjection(Contract):
    # Each target is bounded; the complete host snapshot is independently bounded.
    # Do not hash this aggregate with the 16-KiB individual command encoder.
    records: Annotated[tuple[IngressRecord, ...], Field(max_length=MAX_ORIGINS)]

    @model_validator(mode="after")
    def unique_targets(self):
        for field in ("operator_id", "workspace_id", "binding_id", "public_origin"):
            values = [getattr(item, field) for item in self.records]
            if len(values) != len(set(values)):
                raise ValueError("Ingress ownership must be unique.")
        return self
