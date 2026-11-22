"""Explicit claims only: viewing a saved form never takes over its edit authority."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

from app.modules.hosted_access.domain.models import HostedAccessError
from app.platform.actor_context import current_operator_actor
from app.platform.api_errors import api_problem


class DraftLeaseInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")
    expectedRevision: StrictInt = Field(ge=0)
    takeover: StrictBool = False
    renew: StrictBool = False


class DraftLeaseResponse(BaseModel):
    expiresAt: datetime
    renewedAt: datetime


def build_draft_lease_router(service=None, deployment=None):
    router = APIRouter()

    @router.post(
        "/api/hosted/drafts/{record_id}/lease",
        response_model=DraftLeaseResponse,
        operation_id="claimHostedDraftLease",
    )
    def claim(record_id: UUID, data: DraftLeaseInput, request: Request):
        if service is None:
            raise api_problem(404, "hosted_mode_required", "Hosted drafts are not enabled.")
        if deployment is not None and "records.write" not in deployment.capabilities:
            raise HostedAccessError(
                "hosted_capability_forbidden", "Read-only access cannot claim edits.", 403
            )
        actor = request.state.hosted_actor if deployment else current_operator_actor()
        if actor is None or actor.session_reference is None:
            raise HostedAccessError("hosted_session_required", "Sign in to claim editing.")
        result = service.claim(
            str(record_id),
            actor,
            token=data.token,
            expected_revision=data.expectedRevision,
            takeover=data.takeover,
            renew=data.renew,
        )
        return {
            "expiresAt": datetime.fromtimestamp(result["expires_at"], UTC),
            "renewedAt": datetime.fromtimestamp(result["renewed_at"], UTC),
        }

    return router
