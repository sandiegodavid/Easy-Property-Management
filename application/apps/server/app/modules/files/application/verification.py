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
                    actor_kind="system",
                ))
            counts[state] += 1
        # A single-file repair verifies only that file.  A full verification is
        # also the explicit storage-inventory pass, including orphan discovery.
        reconciliation = {"local": {"referenced": 0, "orphaned": 0, "missing": 0, "unverifiable": 0},
                          "s3": {"referenced": 0, "orphaned": 0, "missing": 0, "unverifiable": 0}}
        complete = file_id is None
        if file_id is None:
            by_provider: dict[str, list[object]] = {}
            for item in candidates:
                by_provider.setdefault(item.storage_provider, []).append(item)
            for provider, items in by_provider.items():
                store = self.stores.get(provider)
                if store is None:
                    raise FileError("The configured content store is unavailable.", "file_provider_unavailable")
                if provider == "local" and hasattr(store, "reconcile"):
                    result = store.reconcile({item.local_relative_path for item in items if item.local_relative_path})
                    reconciliation["local"] = {key: len(value) for key, value in result.items()}
                elif provider == "s3" and hasattr(store, "reconcile"):
                    retained = {(item.s3_bucket, item.s3_object_key, item.s3_version_id)
                                for item in items
                                if item.s3_bucket and item.s3_object_key and item.s3_version_id}
                    seen: set[tuple[str, str, str]] = set()
                    orphaned: set[tuple[str, str, str]] = set()
                    unverifiable: set[tuple[str, str, str]] = set()
                    cursor = None
                    cursors: set[str] = set()
                    while True:
                        page = store.reconcile(retained, cursor)
                        seen.update(page.referenced)
                        orphaned.update(page.orphaned)
                        unverifiable.update(page.unverifiable)
                        if not page.incomplete:
                            break
                        cursor = page.continuation
                        if cursor is None or cursor in cursors:  # Defensive: never claim a broken page stream complete.
                            complete = False
                            break
                        cursors.add(cursor)
                    missing = retained - seen
                    reconciliation["s3"] = {"referenced": len(seen), "orphaned": len(orphaned),
                                              "missing": len(missing), "unverifiable": len(unverifiable)}
        return {"complete": complete, "files": len(candidates), "states": counts,
                "reconciliation": reconciliation}
