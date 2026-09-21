"""Fast test-only encryption fixture for feature backup round-trip tests."""

from __future__ import annotations

from contextlib import ContextDecorator
from unittest.mock import patch

from cryptography.hazmat.primitives.kdf.scrypt import Scrypt as ProductionScrypt


def _fast_scrypt(*args, **kwargs):
    """Keep archive headers production-valid while making KDF work inexpensive."""
    kwargs["n"] = 2
    return ProductionScrypt(*args, **kwargs)


class fast_backup_encryption(ContextDecorator):
    """Use a small scrypt cost for a feature test's complete backup pipeline.

    Workspace archive tests intentionally use the real implementation to cover the
    production KDF parameters.  Feature tests use this fixture only to avoid
    repeatedly paying that cost while still encrypting, validating, and restoring.
    """

    def __enter__(self):
        self._patcher = patch(
            "app.modules.workspace.infrastructure.encrypted_archive.Scrypt",
            side_effect=_fast_scrypt,
        )
        self._patcher.start()
        return self

    def __exit__(self, *exc_info):
        self._patcher.stop()
        return False
