"""Writer-owned explicit FILE-001 storage verification."""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.modules.files.application.errors import FileError
from app.modules.files.application.ports import FileAuditChange, FileContentStore, FileUnitOfWork


class FileStorageVerificationService:
    def __init__(self, unit_of_work: FileUnitOfWork, stores: dict[str, FileContentStore]) -> None:
        self.unit_of_work = unit_of_work
        self.stores = stores

    def verify(self, file_id: str | None = None) -> dict[str, object]:
        """Verify exact retained bytes without letting reads mutate state."""
        candidates = self.unit_of_work.files_for_verification()
        if file_id is not None:
            candidates = [item for item in candidates if item.id == file_id]
            if not candidates:
                raise FileError("File record was not found.", "file_not_found")
        counts = {"available": 0, "missing": 0, "quarantined": 0}
        for item in candidates:
            current = item.storage_state
            try:
                store = self.stores.get(item.storage_provider)
                if store is None:
                    raise FileError("The configured content store is unavailable.", "file_provider_unavailable")
                path = store.path_for(item)
                if item.storage_provider == "s3":
                    path.unlink(missing_ok=True)
                state = "available"
            except FileError as error:
                if error.code == "file_provider_unavailable":
                    # An outage is not evidence loss and must not change state.
                    raise
                state = "missing" if error.code == "file_content_unavailable" else "quarantined"
            if state == "available":
                verified_at = datetime.now(UTC).isoformat()
            else:
                verified_at = item.verified_at
            if state != current or state == "available":
                before = {"storageState": current, "verifiedAt": item.verified_at}
                after = {"storageState": state, "verifiedAt": verified_at}
                self.unit_of_work.replace_storage_verification(item, state, verified_at, FileAuditChange(
                    "file", item.id, "storage_verified", after, "file_storage_verification", str(uuid4()), before,
                ))
            counts[state] += 1
        return {"complete": True, "files": len(candidates), "states": counts}
