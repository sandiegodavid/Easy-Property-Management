"""H03.1 proof input/assertion contracts, not an executable qualification driver."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.modules.hosted_access.application.identity_setup import IdentityPolicy
from app.platform.hosted_contracts.semantic import SemanticRequest, semantic_hash
from app.platform.hosted_contracts.values import CanonicalId, Reference, RequestHash
from app.platform.hosted_proofs.models import Level, Proof, ProofReport, Result

ASSIGNMENT_COUNT = 2
CONTEXT_COUNT = 4
IDENTITY_SPEC_REVISION = 2

IDENTITY_CASES = (
    "google_email_identity",
    "exact_invitation_claim",
    "browser_origin_state_binding",
    "single_use_handoff",
    "cross_workspace_role_denial",
    "host_only_cookie_csrf",
    "mfa_step_up",
    "disable_rebind_logout",
    "no_secret_url_log",
    "multi_device_draft_fences",
    "local_mode_independent",
    "renewal_cap_and_lineage",
    "identity_dependency_cleanup",
    "provider_outage_deadlines",
)


class IdentityProofInputs(SemanticRequest):
    version: Literal[1] = 1
    setup_sha256: RequestHash
    policy_sha256: RequestHash
    source_commit: Annotated[str, Field(strict=True, pattern=r"^[a-f0-9]{40}$")]
    assignments: tuple[CanonicalId, CanonicalId]
    admin_principal_id: CanonicalId
    browser_contexts: tuple[Reference, Reference, Reference, Reference]
    clock: Literal["fixed_component", "actual_provider"]
    level: Literal["component", "deployed_browser"]
    adapter: Literal["isolated_development", "managed_provider"]
    provider_configuration_sha256: RequestHash | None

    @model_validator(mode="after")
    def independent_contexts(self):
        if (
            len(set(self.assignments)) != ASSIGNMENT_COUNT
            or len(set(self.browser_contexts)) != CONTEXT_COUNT
        ):
            raise ValueError(
                "Proof requires two independent assignments and four browser contexts."
            )
        if self.policy_sha256 != semantic_hash(IdentityPolicy()):
            raise ValueError("Proof must pin the accepted identity method/session policy.")
        if self.level == "deployed_browser":
            if (self.clock, self.adapter) != (
                "actual_provider",
                "managed_provider",
            ) or self.provider_configuration_sha256 is None:
                raise ValueError(
                    "Deployed proof requires actual provider clock/configuration and adapter."
                )
        elif (self.clock, self.adapter) != ("fixed_component", "isolated_development"):
            raise ValueError("Component evidence must identify its isolated fixed-clock adapter.")
        return self


class IdentityAssertions(SemanticRequest):
    """Observed values required for an overall identity pass, supplied by later driver.

    Verifying this shape neither authenticates evidence nor executes a negative case.
    The generic report still requires every case, its pins and retained observations.
    """

    version: Literal[1] = 1
    methods: tuple[Literal["google"], Literal["email_link"]]
    admin_method: Literal["google_totp"]
    email_provenance: Literal["backend_sign_in_with_email_link"]
    completed_mfa_proven: Literal[True]
    wrong_realm_denied: Literal[True]
    continuation_swaps_denied: Literal[True]
    same_link_race_single_pair: Literal[True]
    bearer_replays: Literal[0]
    maximum_live_sessions: Annotated[int, Field(strict=True, ge=1, le=32)]
    renewal_lineage_unchanged: Literal[True]
    revoked_lineage_not_revived: Literal[True]
    freshness_ms: Annotated[int, Field(strict=True, ge=0, le=300000)]
    provider_cookie_ms: Annotated[int, Field(strict=True, gt=0, le=1209600000)]
    remembered_lineage_ms: Annotated[int, Field(strict=True, gt=0, le=2592000000)]
    admin_session_ms: Annotated[int, Field(strict=True, gt=0, le=28800000)]
    retained_unknown_results: Literal[True]
    cleanup_restricts_live_dependencies: Literal[True]
    business_export_contains_auth: Literal[False]
    secrets_in_retained_urls_logs: Literal[False]
    unavoidable_email_action_scrubbed: Literal[True]
    local_mode_without_cloud: Literal[True]


def validate_identity_report(
    inputs: IdentityProofInputs, report: ProofReport, assertions: IdentityAssertions | None
) -> None:
    """Additional assertion gate after generic validate_report; no release authority."""
    if report.proof != Proof.IDENTITY or report.environment.level != Level(inputs.level):
        raise ValueError("Identity report must retain its requested proof level.")
    if report.source_commit is not None and report.source_commit != inputs.source_commit:
        raise ValueError("Identity report source does not match its pinned inputs.")
    if report.invocation is not None and report.invocation.input_manifest_sha256 != semantic_hash(
        inputs
    ):
        raise ValueError("Identity report must pin its exact canonical input manifest.")
    if {case.case_id for case in report.cases} != set(IDENTITY_CASES):
        raise ValueError("Identity report must include each accepted H03 case.")
    if report.status == Result.PASSED and assertions is None:
        raise ValueError("An identity pass requires its typed observed assertions.")
    if report.status in {Result.UNAVAILABLE, Result.NOT_RUN} and assertions is not None:
        raise ValueError("Unavailable/unrun identity reports cannot invent observed assertions.")
