"""Strict shared hosted values, aligned with the schema master's conventions."""

from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StrictInt, StrictStr

MAX_INTEGER = 2**63 - 1
MAX_RECORD_BYTES = 16 * 1024


def _canonical_id(value: str) -> str:
    if str(UUID(value)) != value:
        raise ValueError("A canonical lowercase UUID is required.")
    return value


CanonicalId = Annotated[
    StrictStr, Field(min_length=36, max_length=36), AfterValidator(_canonical_id)
]
Revision = Annotated[StrictInt, Field(ge=1, le=MAX_INTEGER)]
AccessEpoch = Revision
Count = Annotated[StrictInt, Field(ge=0, le=MAX_INTEGER)]
EpochMillis = Count
RequestHash = Annotated[StrictStr, Field(min_length=64, max_length=64, pattern=r"^[a-f0-9]+$")]
SafeCode = Annotated[StrictStr, Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_]*$")]
Reference = Annotated[
    StrictStr, Field(min_length=1, max_length=1024, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
]
IdempotencyKey = Annotated[
    StrictStr, Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, validate_default=True)


class Component(StrEnum):
    ADMIN = "admin"
    OPERATOR = "operator"
    TENANT = "tenant"
    OWNER = "owner"


class DeploymentScope(Contract):
    kind: Literal["deployment"] = "deployment"


class WorkspaceScope(Contract):
    kind: Literal["workspace"] = "workspace"
    operator_id: CanonicalId
    workspace_id: CanonicalId


Scope = Annotated[DeploymentScope | WorkspaceScope, Field(discriminator="kind")]


DisplayName = Annotated[StrictStr, Field(min_length=1, max_length=120)]
EmailAddress = Annotated[
    StrictStr, Field(min_length=3, max_length=254, pattern=r"^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+$")
]
Explanation = Annotated[StrictStr, Field(min_length=1, max_length=1000)]

PublicSlug = Annotated[
    StrictStr, Field(min_length=1, max_length=63, pattern=r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")
]
