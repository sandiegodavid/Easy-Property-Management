"""Non-portable local secret storage for optional unattended backups."""

from __future__ import annotations

from typing import Protocol

import keyring
from keyring.errors import KeyringError


class SecretStoreError(RuntimeError):
    """Raised when the operating-system credential store cannot be used."""


class BackupSecretStore(Protocol):
    def get_passphrase(self, workspace_id: str) -> str | None: ...

    def set_passphrase(self, workspace_id: str, passphrase: str) -> None: ...

    def delete_passphrase(self, workspace_id: str) -> None: ...


class KeyringBackupSecretStore:
    """Stores an opt-in automatic-backup passphrase in the OS credential store."""

    service_name = "Easy Property Management Backup"

    def get_passphrase(self, workspace_id: str) -> str | None:
        try:
            return keyring.get_password(self.service_name, workspace_id)
        except KeyringError as error:
            raise SecretStoreError(f"Unable to read the automatic-backup credential: {error}") from error

    def set_passphrase(self, workspace_id: str, passphrase: str) -> None:
        try:
            keyring.set_password(self.service_name, workspace_id, passphrase)
        except KeyringError as error:
            raise SecretStoreError(f"Unable to save the automatic-backup credential: {error}") from error

    def delete_passphrase(self, workspace_id: str) -> None:
        try:
            keyring.delete_password(self.service_name, workspace_id)
        except keyring.errors.PasswordDeleteError:
            return
        except KeyringError as error:
            raise SecretStoreError(f"Unable to remove the automatic-backup credential: {error}") from error
