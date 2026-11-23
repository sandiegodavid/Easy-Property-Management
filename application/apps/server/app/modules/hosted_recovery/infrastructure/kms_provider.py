"""Host-side GCP Cloud KMS envelope wrapper (used only inside epm-backup-proxy)."""

from __future__ import annotations

import base64
from collections.abc import Callable
import json
import os
import ssl
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.modules.hosted_recovery.domain.models import (
    AES_GCM_NONCE_BYTES,
    AES_KEY_BYTES,
    BackupProxyUnavailable,
    RecoveryCryptoError,
    validate_kms_key_ref,
)

CLOUD_KMS_API_ROOT = "https://cloudkms.googleapis.com/v1"
GCP_METADATA_TOKEN_URL = (
    "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"
)


def fetch_gcp_metadata_token(*, timeout_seconds: float = 5.0) -> str:
    """Fetch an OAuth2 access token from the GCP VM metadata server."""
    request = Request(
        GCP_METADATA_TOKEN_URL,
        headers={"Metadata-Flavor": "Google"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError) as error:
        raise BackupProxyUnavailable("Failed to obtain GCP metadata access token.") from error
    token = payload.get("access_token")
    if not isinstance(token, str) or not token:
        raise BackupProxyUnavailable("GCP metadata server returned an invalid token response.")
    return token


class CloudKmsEnvelopeProvider:
    """GCP Cloud KMS REST v1 envelope wrap/unwrap provider with strict key_ref validation."""

    def __init__(
        self,
        *,
        token_supplier: Callable[[], str] = fetch_gcp_metadata_token,
        api_root: str = CLOUD_KMS_API_ROOT,
        timeout_seconds: float = 10.0,
        opener=None,
    ):
        if not api_root.startswith("https://"):
            raise ValueError("Cloud KMS API root must use HTTPS.")
        self._token_supplier = token_supplier
        self._api_root = api_root.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._ssl_context = ssl.create_default_context()
        self._opener = opener

    def _call(self, url: str, body: dict[str, str]) -> dict[str, object]:
        token = self._token_supplier()
        if not token:
            raise BackupProxyUnavailable("Empty Cloud KMS bearer token.")
        encoded = json.dumps(body, separators=(",", ":")).encode("utf-8")
        request = Request(
            url,
            data=encoded,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            if self._opener is not None:
                response_bytes = self._opener(request, self._timeout_seconds)
            else:
                with urlopen(
                    request,
                    timeout=self._timeout_seconds,
                    context=self._ssl_context,
                ) as response:
                    response_bytes = response.read()
        except HTTPError as error:
            if error.code in {400, 403}:
                raise RecoveryCryptoError("Cloud KMS rejected cryptographic request.") from error
            raise BackupProxyUnavailable("Cloud KMS endpoint error.") from error
        except (URLError, OSError) as error:
            raise BackupProxyUnavailable("Cloud KMS is unreachable.") from error
        try:
            parsed = json.loads(response_bytes.decode("utf-8"))
        except ValueError as error:
            raise BackupProxyUnavailable("Cloud KMS returned invalid JSON.") from error
        if not isinstance(parsed, dict):
            raise BackupProxyUnavailable("Cloud KMS returned unexpected payload.")
        return parsed

    def wrap_dek(self, key_ref: str, plaintext_dek: bytes, *, aad: bytes) -> bytes:
        validated_key = validate_kms_key_ref(key_ref)
        if len(plaintext_dek) != AES_KEY_BYTES:
            raise RecoveryCryptoError("Plaintext DEK must be 32 bytes.")
        url = f"{self._api_root}/{validated_key}:encrypt"
        payload = self._call(
            url,
            {
                "plaintext": base64.b64encode(plaintext_dek).decode("ascii"),
                "additionalAuthenticatedData": base64.b64encode(aad).decode("ascii"),
            },
        )
        raw_ciphertext = payload.get("ciphertext")
        if not isinstance(raw_ciphertext, str) or not raw_ciphertext:
            raise BackupProxyUnavailable("Cloud KMS encrypt response missing ciphertext.")
        try:
            return base64.b64decode(raw_ciphertext.encode("ascii"), validate=True)
        except ValueError as error:
            raise BackupProxyUnavailable(
                "Cloud KMS returned invalid ciphertext encoding."
            ) from error

    def unwrap_dek(self, key_ref: str, wrapped_dek: bytes, *, aad: bytes) -> bytes:
        validated_key = validate_kms_key_ref(key_ref)
        if not wrapped_dek or len(wrapped_dek) > 4096:
            raise RecoveryCryptoError("Wrapped DEK size is invalid.")
        # Cloud KMS decrypt targets the parent cryptoKey resource even if key_ref has a version.
        decrypt_target = validated_key.split("/cryptoKeyVersions/", 1)[0]
        url = f"{self._api_root}/{decrypt_target}:decrypt"
        payload = self._call(
            url,
            {
                "ciphertext": base64.b64encode(wrapped_dek).decode("ascii"),
                "additionalAuthenticatedData": base64.b64encode(aad).decode("ascii"),
            },
        )
        raw_plaintext = payload.get("plaintext")
        if not isinstance(raw_plaintext, str) or not raw_plaintext:
            raise RecoveryCryptoError("Cloud KMS decrypt response missing plaintext.")
        try:
            plaintext = base64.b64decode(raw_plaintext.encode("ascii"), validate=True)
        except ValueError as error:
            raise RecoveryCryptoError("Cloud KMS returned invalid plaintext encoding.") from error
        if len(plaintext) != AES_KEY_BYTES:
            raise RecoveryCryptoError("Cloud KMS unwrapped DEK has unexpected length.")
        return plaintext


class LocalAesKmsProvider:
    """In-memory AES-256-GCM KEK wrapper for component proofs and tests (never for production)."""

    def __init__(self, keys: dict[str, bytes]):
        self._keys: dict[str, bytes] = {}
        for key_ref, material in keys.items():
            validated = validate_kms_key_ref(key_ref)
            if len(material) != AES_KEY_BYTES:
                raise ValueError("KEK material must be 32 bytes.")
            self._keys[validated] = material

    def _resolve_key(self, key_ref: str) -> bytes:
        validated = validate_kms_key_ref(key_ref)
        if validated in self._keys:
            return self._keys[validated]
        parent = validated.split("/cryptoKeyVersions/", 1)[0]
        if parent in self._keys:
            return self._keys[parent]
        raise RecoveryCryptoError("Unknown KMS key_ref.")

    def wrap_dek(self, key_ref: str, plaintext_dek: bytes, *, aad: bytes) -> bytes:
        if len(plaintext_dek) != AES_KEY_BYTES:
            raise RecoveryCryptoError("Plaintext DEK must be 32 bytes.")
        kek = self._resolve_key(key_ref)
        nonce = os.urandom(AES_GCM_NONCE_BYTES)
        return nonce + AESGCM(kek).encrypt(nonce, plaintext_dek, aad)

    def unwrap_dek(self, key_ref: str, wrapped_dek: bytes, *, aad: bytes) -> bytes:
        if len(wrapped_dek) <= AES_GCM_NONCE_BYTES + 16:
            raise RecoveryCryptoError("Wrapped DEK is truncated.")
        kek = self._resolve_key(key_ref)
        nonce = wrapped_dek[:AES_GCM_NONCE_BYTES]
        ciphertext = wrapped_dek[AES_GCM_NONCE_BYTES:]
        try:
            dek = AESGCM(kek).decrypt(nonce, ciphertext, aad)
        except InvalidTag as error:
            raise RecoveryCryptoError("KMS unwrap authentication failed.") from error
        if len(dek) != AES_KEY_BYTES:
            raise RecoveryCryptoError("Unwrapped DEK length mismatch.")
        return dek
