"""H03.1 protected identity inputs; validation is not provider configuration or authority."""

from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import AfterValidator, Field, model_validator

from app.platform.hosted_contracts.semantic import SemanticRequest
from app.platform.hosted_contracts.values import Reference, RequestHash, Revision

MINUTE = 60_000
HOUR = 60 * MINUTE
DAY = 24 * HOUR
MAX_HOST_LENGTH = 253
MAX_LABEL_LENGTH = 63
MIN_DOMAIN_LABELS = 2


def exact_https_origin(value: str) -> str:
    parsed = urlsplit(value)
    host = parsed.hostname or ""
    if (
        value != "https://" + host
        or not host.isascii()
        or len(host) > MAX_HOST_LENGTH
        or len(host.split(".")) < MIN_DOMAIN_LABELS
        or any(
            not part
            or len(part) > MAX_LABEL_LENGTH
            or part.startswith("-")
            or part.endswith("-")
            or any(not (char.isalnum() or char == "-") for char in part)
            for part in host.split(".")
        )
    ):
        raise ValueError("Use an exact canonical HTTPS origin without a port, path or wildcard.")
    return value


HttpsOrigin = Annotated[str, Field(strict=True, max_length=261), AfterValidator(exact_https_origin)]
ProjectId = Annotated[str, Field(strict=True, pattern=r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")]


class IdentityPolicy(SemanticRequest):
    """Accepted initial policy. Changing a bound requires a new reviewed profile."""

    version: Literal[1] = 1
    attempt_ms: Literal[900_000] = 15 * MINUTE
    handoff_ms: Literal[300_000] = 5 * MINUTE
    continuation_ms: Literal[300_000] = 5 * MINUTE
    remembered_ms: Literal[2_592_000_000] = 30 * DAY
    provider_cookie_ms: Literal[1_209_600_000] = 14 * DAY
    unremembered_ms: Literal[28_800_000] = 8 * HOUR
    admin_session_ms: Literal[28_800_000] = 8 * HOUR
    recent_auth_ms: Literal[900_000] = 15 * MINUTE
    provider_status_ms: Literal[300_000] = 5 * MINUTE
    resend_cooldown_ms: Literal[60_000] = MINUTE
    destination_sends_per_hour: Literal[5] = 5
    network_sends_per_hour: Literal[20] = 20
    max_live_sessions: Literal[32] = 32
    session_page_size: Literal[50] = 50
    max_edit_leases: Literal[128] = 128
    cleanup_batch_size: Literal[100] = 100
    minimum_retention_ms: Literal[86_400_000] = DAY
    private_timeout_ms: Literal[5000] = 5000
    refresh_credential_storage: Literal["none"] = "none"
    browser_provider_persistence: Literal["memory_only"] = "memory_only"


class IdentityRealm(SemanticRequest):
    version: Literal[1] = 1
    alias: Reference
    project_id: ProjectId
    tenant_id: Reference | None
    issuer: str
    audience: str
    operator_methods: tuple[Literal["google"], Literal["email_link"]] = ("google", "email_link")
    admin_method: Literal["google_totp"] = "google_totp"
    email_completion: Literal["backend_sign_in_with_email_link"] = "backend_sign_in_with_email_link"

    @model_validator(mode="after")
    def exact_provider(self):
        if self.issuer != "https://securetoken.google.com/" + self.project_id:
            raise ValueError("Issuer must match the exact configured provider project.")
        if self.audience != self.project_id:
            raise ValueError("Provider audience must equal the configured project.")
        return self


class IdentityOrigins(SemanticRequest):
    central: HttpsOrigin
    admin: HttpsOrigin
    google_callback: str
    email_callback: str

    @model_validator(mode="after")
    def exact_callbacks(self):
        if self.central == self.admin:
            raise ValueError("Admin and central login require distinct origins.")
        if self.google_callback != self.central + "/__/auth/handler":
            raise ValueError("Google callback must use the fixed central provider helper.")
        if self.email_callback != self.central + "/auth/email/continue":
            raise ValueError("Email completion must use the fixed central continuation route.")
        return self


class DependencyPin(SemanticRequest):
    version: Annotated[str, Field(strict=True, pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")]
    sha256: RequestHash


class IdentitySetup(SemanticRequest):
    """Protected setup, not browser input. No credentials or provider observations here.

    Resolvers verify digest-pinned configuration, root custody and credentials later.
    Realm aliases are immutable; reconfiguration requires explicit fenced rebind.
    """

    version: Literal[1] = 1
    revision: Revision
    configuration_state: Literal["selected_not_verified", "verified"]
    realm: IdentityRealm
    origins: IdentityOrigins
    firebase_web: DependencyPin
    firebase_admin: DependencyPin
    provider_config_ref: Reference
    provider_config_sha256: RequestHash | None
    central_signing_key_ref: Reference
    source_signing_key_registry_ref: Reference
    signing_algorithm: Literal["Ed25519"] = "Ed25519"
    key_custody: Literal["owning_service_only_protected_delivery"] = (
        "owning_service_only_protected_delivery"
    )
    rate_store: Literal["central_durable_atomic_buckets"] = "central_durable_atomic_buckets"
    rate_key_ref: Reference
    rate_key_rotation_ms: Annotated[int, Field(strict=True, ge=HOUR, le=DAY)]
    rate_retention_ms: Annotated[int, Field(strict=True, ge=HOUR, le=2 * DAY)]
    deployment_sends_per_day: Annotated[int, Field(strict=True, gt=0)]
    provider_sends_per_day: Annotated[int, Field(strict=True, gt=0)]
    policy: IdentityPolicy = IdentityPolicy()

    @model_validator(mode="after")
    def bounded_mail_and_keys(self):
        if self.configuration_state == "verified" and self.provider_config_sha256 is None:
            raise ValueError("Verified setup requires its inspected provider configuration digest.")
        if self.deployment_sends_per_day >= self.provider_sends_per_day:
            raise ValueError("Deployment mail ceiling must remain below configured provider quota.")
        if self.central_signing_key_ref == self.source_signing_key_registry_ref:
            raise ValueError("Central and source signing custody must be separate.")
        if self.rate_retention_ms < self.rate_key_rotation_ms + HOUR:
            raise ValueError(
                "Rate keys must survive rotation plus the complete active hourly window."
            )
        return self


def require_verified_setup(setup: IdentitySetup) -> None:
    """Precondition only; protected input/artifact/provider checks remain mandatory."""
    if setup.configuration_state != "verified":
        raise ValueError("Managed identity setup has not been independently verified.")


def require_immutable_realm(retained: IdentityRealm, proposed: IdentityRealm) -> None:
    """Protect alias identity; a new alias still needs an audited fenced rebind."""
    if retained.alias == proposed.alias and retained != proposed:
        raise ValueError("An existing identity realm alias cannot be remapped in place.")
