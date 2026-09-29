"""Writer-owned explicit FILE-001 storage verification."""
from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from uuid import uuid4

from app.modules.files.application.errors import FileError
from app.modules.files.application.ports import (FileAuditChange, FileContentStore,
                                                 FileUnitOfWork, FileVerificationConsequences)


def _decode_cursor(value: str | None) -> dict[str, object]:
    if not value:
        return {"cursor": None, "seen": [], "orphaned": [], "unverifiable": []}
    try:
        raw = base64.urlsafe_b64decode(value.encode() + b"=" * (-len(value) % 4))
        state = json.loads(raw)
        if not isinstance(state, dict) or not isinstance(state.get("seen"), list):
            raise ValueError
        return state
    except (ValueError, TypeError, json.JSONDecodeError) as error:
        raise FileError("Storage reconciliation continuation is invalid.") from error


def _encode_cursor(state: dict[str, object]) -> str:
    return base64.urlsafe_b64encode(json.dumps(state, sort_keys=True, separators=(",", ":")).encode()).decode().rstrip("=")


class FileStorageVerificationService:
    def __init__(self, unit_of_work: FileUnitOfWork, stores: dict[str, FileContentStore],
                 consequences: FileVerificationConsequences | None = None) -> None:
        self.unit_of_work = unit_of_work
        self.stores = stores
        self.consequences = consequences

    def verify(self, file_id: str | None = None, *, continuation: str | None = None) -> dict[str, object]:
        """Verify retained bytes and process one bounded S3 inventory page."""
        if file_id is not None and continuation is not None:
            raise FileError("A single-file verification cannot be resumed.")
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
                ), self.consequences)
            counts[state] += 1
        # A single-file repair verifies only that file.  A full verification is
        # also the explicit storage-inventory pass, including orphan discovery.
        reconciliation: dict[str, dict[str, int]] = {}
        scan_complete = file_id is None
        next_continuation: str | None = None
        if file_id is None:
            # Include every configured store: a failed first publication has
            # no retained row yet, but its object is still an orphan.
            by_provider: dict[str, list[object]] = {provider: [] for provider in self.stores}
            for item in candidates:
                by_provider.setdefault(item.storage_provider, []).append(item)
            state = _decode_cursor(continuation)
            for provider, store in self.stores.items():
                items = by_provider.get(provider, [])
                if provider == "local" and hasattr(store, "reconcile"):
                    result = store.reconcile({item.local_relative_path for item in items if item.local_relative_path})
                    reconciliation[provider] = {key: len(value) for key, value in result.items()}
                elif provider == "s3" and hasattr(store, "reconcile"):
                    retained = {(item.s3_bucket, item.s3_object_key, item.s3_version_id)
                                for item in items
                                if item.s3_bucket and item.s3_object_key and item.s3_version_id}
                    page = store.reconcile(retained, state.get("cursor") if continuation else None)
                    seen = {tuple(value) for value in state["seen"] if isinstance(value, list) and len(value) == 3}
                    seen.update(page.referenced)
                    orphaned = list(state["orphaned"]) + [list(value) for value in page.orphaned]
                    unverifiable = list(state["unverifiable"]) + [list(value) for value in page.unverifiable]
                    if page.incomplete:
                        scan_complete = False
                        next_continuation = _encode_cursor({"cursor": page.continuation, "seen": [list(value) for value in sorted(seen)],
                                                            "orphaned": orphaned, "unverifiable": unverifiable})
                    missing = retained - seen if not page.incomplete else set()
                    reconciliation[provider] = {"referenced": len(seen), "orphaned": len(orphaned),
                                                 "missing": len(missing), "unverifiable": len(unverifiable)}
        reconciliation_problems = any(value for result in reconciliation.values() for key, value in result.items() if key != "referenced")
        content_problems = counts["missing"] > 0 or counts["quarantined"] > 0
        # A completed inventory is not necessarily clean.  In particular a
        # corrupt object can remain present at its recorded locator.
        complete = scan_complete and not reconciliation_problems and not content_problems
        if complete and file_id is None:
            resolved = getattr(self.unit_of_work, "record_cleanup_resolved", None)
            if resolved is not None:
                resolved(str(uuid4()))
        outstanding = getattr(self.unit_of_work, "outstanding_cleanup_attentions", lambda: [])()
        return {"complete": complete, "scanComplete": scan_complete,
                "continuation": next_continuation, "files": len(candidates), "states": counts,
                "reconciliation": reconciliation, "cleanupAttention": {"outstanding": len(outstanding)}}
