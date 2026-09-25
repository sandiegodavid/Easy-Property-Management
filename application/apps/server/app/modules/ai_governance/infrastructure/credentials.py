"""AI transport secrets stay device-local and never enter SQLite."""
from __future__ import annotations
import keyring
from keyring.errors import KeyringError
from app.modules.ai_governance.application.ports import AiTransportCredentialStore


class AiCredentialStoreError(RuntimeError):
    pass


class KeyringAiTransportCredentialStore(AiTransportCredentialStore):
    service_name = "Easy Property Management AI Transport"
    def _name(self, workspace_id: str, connection_id: str) -> str: return f"{workspace_id}:{connection_id}"
    def get_credential(self, workspace_id: str, connection_id: str) -> str | None:
        try: return keyring.get_password(self.service_name, self._name(workspace_id, connection_id))
        except KeyringError as error: raise AiCredentialStoreError("Unable to read the AI transport credential.") from error
    def set_credential(self, workspace_id: str, connection_id: str, credential: str) -> None:
        if not isinstance(credential, str) or not credential.strip() or len(credential) > 8_192: raise AiCredentialStoreError("AI credential must be bounded nonblank text.")
        try: keyring.set_password(self.service_name, self._name(workspace_id, connection_id), credential)
        except KeyringError as error: raise AiCredentialStoreError("Unable to save the AI transport credential.") from error
    def delete_credential(self, workspace_id: str, connection_id: str) -> None:
        try: keyring.delete_password(self.service_name, self._name(workspace_id, connection_id))
        except keyring.errors.PasswordDeleteError: return
        except KeyringError as error: raise AiCredentialStoreError("Unable to remove the AI transport credential.") from error
