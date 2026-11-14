"""Protected central-only provider configuration. No environment/local fallback."""

from hashlib import sha256
import os
from pathlib import Path
import stat
from typing import Literal

from pydantic import Field, SecretStr

from app.modules.hosted_access.application.identity_setup import (
    IdentityOrigins,
    IdentityRealm,
    IdentitySetup,
    require_verified_setup,
)
from app.modules.hosted_access.application.managed_provider import ProviderUnavailable
from app.modules.hosted_access.infrastructure.firebase_rest import (
    ID_CERTS,
    SESSION_CERTS,
    FirebaseRest,
    ProviderHttp,
)
from app.modules.hosted_access.infrastructure.firebase_tokens import (
    CertificateCache,
    FirebaseTokenVerifier,
)

from app.platform.hosted_contracts.values import Contract

MAX_CONFIGURATION = 65536


class ProviderConfiguration(Contract):
    version: Literal[1] = 1
    realm: IdentityRealm
    origins: IdentityOrigins
    api_key: SecretStr = Field(min_length=20, max_length=256)
    google_enabled: Literal[True]
    email_link_enabled: Literal[True]
    totp_enabled: Literal[True]
    provider_email_sends_per_day: int = Field(strict=True, gt=0)


def load_provider_configuration(
    path: Path, setup: IdentitySetup, *, component: str
) -> ProviderConfiguration:
    """Protected composition supplies the path; never expose this as a request field.

    The owning setup process independently inspects provider settings before sealing
    this digest. A locally edited boolean never establishes provider acceptance.
    No service-account credential or browser/session bearer belongs in this file.
    """
    if component != "central_identity":
        raise ProviderUnavailable()
    try:
        require_verified_setup(setup)
        if not path.is_absolute() or path.parent.resolve() != path.parent:
            raise ValueError()
        parent = path.parent.stat()
        if parent.st_uid not in {0, os.geteuid()} or stat.S_IMODE(parent.st_mode) & 0o077:
            raise ValueError()
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            before = os.fstat(descriptor)
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1
                or before.st_uid not in {0, os.geteuid()}
                or stat.S_IMODE(before.st_mode) & 0o077
                or before.st_size > MAX_CONFIGURATION
            ):
                raise ValueError()
            content = os.read(descriptor, MAX_CONFIGURATION + 1)
            after = os.fstat(descriptor)
            if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            ):
                raise ValueError()
        finally:
            os.close(descriptor)
        if sha256(content).hexdigest() != setup.provider_config_sha256:
            raise ValueError()
        value = ProviderConfiguration.model_validate_json(content)
        if (
            value.realm != setup.realm
            or value.origins != setup.origins
            or value.provider_email_sends_per_day != setup.provider_sends_per_day
        ):
            raise ValueError()
        return value
    except OSError, ValueError, TypeError:
        raise ProviderUnavailable() from None


def build_central_provider(
    path: Path, setup: IdentitySetup, *, component: str, bearer, rate_admission, proxy=None
):
    """Compose the protected central adapter with deployment-owned credentials and rate store."""
    configuration = load_provider_configuration(path, setup, component=component)
    if not callable(bearer) or not callable(getattr(rate_admission, "reserve_email", None)):
        raise ProviderUnavailable()
    http = ProviderHttp(proxy)

    def certificates(url):
        def fetch():
            response = http.request(url)
            return response.data, response.cache_seconds

        return CertificateCache(fetch)

    verifier = FirebaseTokenVerifier(
        configuration.realm, certificates(ID_CERTS), certificates(SESSION_CERTS)
    )
    return FirebaseRest(
        setup, configuration.api_key, bearer, verifier, http=http, rate_admission=rate_admission
    )
