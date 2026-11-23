"""H03.1 auth-only ingress contracts. H03.6 owns dispatch and native qualification.

These models do not alter H02's closed gateway projection or register public routes.
Protected manifests resolve exact artifacts/endpoints; callers supply only registered
IDs and pins. An auth-ready observation is not business-routing eligibility.
"""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.modules.host_agent.application.effect_contracts import EffectIdentity
from app.modules.hosted_access.application.identity_setup import HttpsOrigin
from app.platform.hosted_contracts.semantic import SemanticRequest
from app.platform.hosted_contracts.values import (
    CanonicalId,
    EpochMillis,
    Reference,
    RequestHash,
    Revision,
)

HELD_AUTH_ROUTES = (("GET", "/auth/start"), ("POST", "/auth/complete"), ("GET", "/auth/status"))
CENTRAL_IDENTITY_ROUTES = (
    ("GET", "/auth/start"),
    ("POST", "/auth/email-link"),
    ("POST", "/auth/complete"),
    ("GET", "/auth/email/continue"),
    ("POST", "/auth/email/continue"),
    ("GET", "/__/auth/handler"),
    ("GET", "/__/auth/handler.js"),
    ("GET", "/__/auth/iframe"),
    ("GET", "/__/auth/iframe.js"),
    ("GET", "/__/auth/experiments.js"),
    ("GET", "/__/firebase/init.json"),
)
ADMIN_IDENTITY_ROUTES = (
    ("GET", "/auth/start"),
    ("POST", "/auth/complete"),
    ("GET", "/api/admin/session"),
    ("POST", "/auth/logout"),
)
ADMIN_LITE_ROUTES = (
    *ADMIN_IDENTITY_ROUTES,
    ("GET", "/api/admin/bootstrap"),
    ("GET", "/api/admin/operators"),
    ("POST", "/api/admin/operators"),
    ("GET", "/api/admin/operators/{operator_id}"),
    ("POST", "/api/admin/operators/{operator_id}/invitations"),
    ("POST", "/api/admin/operators/{operator_id}/invitations/{invitation_id}/delivered"),
    ("POST", "/api/admin/operators/{operator_id}/refresh"),
)
ADMIN_H05_ROUTES = (
    *ADMIN_LITE_ROUTES,
    ("POST", "/api/admin/operators/{operator_id}/repair-runtime"),
    ("GET", "/api/admin/operations/{operation_id}"),
    ("GET", "/api/admin/recovery/status"),
    ("GET", "/api/admin/recovery/points"),
    ("POST", "/api/admin/recovery/preview"),
    ("POST", "/api/admin/recovery/confirm"),
    ("POST", "/api/admin/recovery/accept"),
    ("POST", "/api/admin/recovery/reconstruct"),
)
WORKSPACE_FORBIDDEN_PREFIXES = (
    "/admin",
    "/__/auth",
    "/__/firebase",
    "/internal",
    "/debug",
    "/.well-known",
    "/metrics",
)
WORKSPACE_ALLOWED_METHODS = ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE")
Route = tuple[Literal["GET", "POST"], Annotated[str, Field(strict=True, max_length=100)]]


class IdentityCookiePolicy(SemanticRequest):
    central: Literal["__Host-epm-central"] = "__Host-epm-central"
    admin: Literal["__Host-epm-admin"] = "__Host-epm-admin"
    operator: Literal["__Host-epm-session"] = "__Host-epm-session"
    central_challenge: Literal["__Host-epm-central-challenge"] = "__Host-epm-central-challenge"
    source_challenge: Literal["__Host-epm-source-challenge"] = "__Host-epm-source-challenge"
    secure: Literal[True] = True
    http_only: Literal[True] = True
    path: Literal["/"] = "/"
    domain: None = None
    same_site: Literal["Lax"] = "Lax"
    unsafe_requests: Literal["exact_origin_and_session_csrf"] = "exact_origin_and_session_csrf"
    callback_exception: Literal["completion_post_exact_central_origin_and_source_challenge"] = (
        "completion_post_exact_central_origin_and_source_challenge"
    )


class AuthRouteManifest(SemanticRequest):
    version: Literal[1] = 1
    component_id: CanonicalId
    artifact_sha256: RequestHash
    private_endpoint_id: CanonicalId
    routes: tuple[
        tuple[Literal["GET"], Literal["/auth/start"]],
        tuple[Literal["POST"], Literal["/auth/complete"]],
        tuple[Literal["GET"], Literal["/auth/status"]],
    ] = HELD_AUTH_ROUTES


class SharedIdentityManifest(SemanticRequest):
    version: Literal[1] = 1
    component_id: CanonicalId
    artifact_sha256: RequestHash
    private_endpoint_id: CanonicalId
    central_origin: HttpsOrigin
    admin_origin: HttpsOrigin
    owning_login_origin: HttpsOrigin
    route_policy: Literal[
        "separate_exact_host_method_allowlists_v1",
        "separate_exact_host_method_allowlists_v2",
        "separate_exact_host_method_allowlists_v3",
    ] = "separate_exact_host_method_allowlists_v1"
    cookie_policy: Literal["distinct_secure_httponly_host_path_lax_v1"] = (
        "distinct_secure_httponly_host_path_lax_v1"
    )
    cookies: IdentityCookiePolicy = IdentityCookiePolicy()
    central_routes: Annotated[tuple[Route, ...], Field(max_length=11)] = CENTRAL_IDENTITY_ROUTES
    admin_routes: Annotated[tuple[Route, ...], Field(max_length=24)] = ADMIN_IDENTITY_ROUTES

    @model_validator(mode="after")
    def owning_origins(self):
        expected_admin_routes = {
            "separate_exact_host_method_allowlists_v1": ADMIN_IDENTITY_ROUTES,
            "separate_exact_host_method_allowlists_v2": ADMIN_LITE_ROUTES,
            "separate_exact_host_method_allowlists_v3": ADMIN_H05_ROUTES,
        }[self.route_policy]
        if (
            self.central_routes != CENTRAL_IDENTITY_ROUTES
            or self.admin_routes != expected_admin_routes
        ):
            raise ValueError(
                "Shared identity routes require the exact versioned host/method allowlists."
            )
        if (
            self.central_origin != self.owning_login_origin
            or self.admin_origin == self.central_origin
        ):
            raise ValueError(
                "Shared manifest must match the owning central origin and separate Admin."
            )
        return self


class ApplyAuthRoutes(SemanticRequest):
    version: Literal[1] = 1
    action: Literal["apply_auth_routes"] = "apply_auth_routes"
    effect: EffectIdentity
    access_epoch: Revision
    expected_ingress_revision: Revision
    manifest_ref: Reference
    manifest_sha256: RequestHash

    @model_validator(mode="after")
    def auth_effect(self):
        if self.effect.kind != self.action:
            raise ValueError("Auth routes require their original auth-route host effect.")
        return self


class AuthRouteObservation(SemanticRequest):
    version: Literal[1] = 1
    binding_id: CanonicalId
    resource_generation: Revision
    access_epoch: Revision
    ingress_revision: Revision
    desired_state: Literal["held", "eligible", "blocked"]
    auth_route_state: Literal["closed", "ready"]
    auth_access_epoch: Revision | None
    auth_manifest_ref: Reference | None
    auth_manifest_sha256: RequestHash | None
    auth_operation_id: CanonicalId | None
    auth_verified_at: EpochMillis | None

    @model_validator(mode="after")
    def complete_current_evidence(self):
        evidence = (
            self.auth_access_epoch,
            self.auth_manifest_ref,
            self.auth_manifest_sha256,
            self.auth_operation_id,
            self.auth_verified_at,
        )
        if self.auth_route_state == "closed":
            if any(value is not None for value in evidence):
                raise ValueError("Closed auth routes cannot retain readiness evidence.")
        elif (
            any(value is None for value in evidence)
            or self.desired_state == "blocked"
            or self.auth_access_epoch != self.access_epoch
        ):
            raise ValueError(
                "Ready auth routes require complete current non-blocked host evidence."
            )
        return self


class WorkspaceRouteManifest(SemanticRequest):
    """H05.7 positive Operator workspace route manifest (D9), gated by verified recovery proof."""

    version: Literal[1] = 1
    component_id: CanonicalId
    artifact_sha256: RequestHash
    private_endpoint_id: CanonicalId
    route_policy: Literal["operator_workspace_exact_host_v1"] = "operator_workspace_exact_host_v1"
    allowed_methods: tuple[
        Literal["GET"],
        Literal["HEAD"],
        Literal["POST"],
        Literal["PUT"],
        Literal["PATCH"],
        Literal["DELETE"],
    ] = WORKSPACE_ALLOWED_METHODS
    forbidden_prefixes: tuple[str, ...] = WORKSPACE_FORBIDDEN_PREFIXES
    websocket_allowed: Literal[False] = False
    recovery_proof_ref: Reference

    @model_validator(mode="after")
    def require_forbidden_prefixes(self):
        if self.forbidden_prefixes != WORKSPACE_FORBIDDEN_PREFIXES:
            raise ValueError("WorkspaceRouteManifest must retain exact forbidden prefix list.")
        return self


class WorkspaceRouteObservation(SemanticRequest):
    """Host-verified positive workspace routing evidence bound to verified H05 protection."""

    version: Literal[1] = 1
    binding_id: CanonicalId
    resource_generation: Revision
    access_epoch: Revision
    desired_state: Literal["eligible"] = "eligible"
    workspace_route_state: Literal["ready", "closed"]
    workspace_manifest_sha256: RequestHash
    source_identity_proof_ref: Reference
    resource_readiness_proof_ref: Reference
    verified_recovery_point_id: CanonicalId
    observed_at: EpochMillis
