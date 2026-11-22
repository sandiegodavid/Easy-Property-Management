# H04.5 hosted business composition

H04.5 replaces the legacy 250 MiB loop-volume storage budget in
`ManagedBusiness` with the two-layer H04 Free storage admission adapter, wires
`GET /api/hosted/settings` into `DestinationHTTP` and `operator_entry.py`, and
validates hosted business, Settings, two-device draft lease, and `507`
exhaustion flows through the full `create_app()` composition per
[HOSTED_MVP_H04_DESIGN.md](HOSTED_MVP_H04_DESIGN.md) (decision D5).

- **Two-layer Free storage admission**
  (`hosted_access/infrastructure/free_storage_admission.py`):
  `FreeStorageAdmission` combines:
  1. Read-only physical project-quota headroom checks across `workspace`,
     `control`, and `scratch` (`PhysicalQuotaHeadroom`: byte and inode floors,
     failing closed with `507 hosted_storage_quota_exceeded` or `503
     hosted_storage_unavailable`).
  2. Durable logical `50,000,000`-byte reservation in `access.sqlite` via
     `UsageAccountingStore`, settling post-commit usage on `2xx`/`3xx`,
     releasing on `4xx`/`HostedAccessError`, and marking `unknown` on
     `5xx`/crash until `reconcile_unknown()`.
- **Hosted business & Settings composition**
  (`hosted_access/api/managed_business.py`,
  `hosted_access/infrastructure/operator_identity_runtime.py`,
  `hosted_access/infrastructure/operator_entry.py`):
  - `ManagedBusiness.dispatch()` passes `source_epoch` and records response
    status on the `ReservationOutcome` handle so logical reservations settle or
    release accurately.
  - `DestinationHTTP` routes `/api/hosted/settings` to the source-owned
    `operator_settings_router` when `usage_reader` and `support_contact` are
    supplied.
  - `operator_entry.py` wires `UsageAccountingStore` (pointing to
    `WorkspacePaths(root=workspace).database`) and `FreeStorageAdmission` into
    `ManagedBusinessInputs`, while keeping deployed `readiness` closed
    (`lambda: False`) until H05 supplies the verified recovery-point gate.

## Local validation

6 focused Python tests passed across `test_h04_hosted_business_composition.py`
(3 end-to-end tests) and `test_h04_source_usage_settings.py` (3 tests).
`ruff check` passed on all new files and `ruff format --check` passed on all 5
modified Python files using `application/pyproject.toml`.

| Area | Observed evidence |
| --- | --- |
| Hosted business & 2 devices | Device A creates a party (`POST /api/parties`), Device B reads it and `GET /api/portfolio/status-summary`; `GET /api/hosted/settings` reflects settled logical usage and honest `unavailable` H05 protection; Device A acquires a draft lease and Device B receives `409` conflict; `/api/workspace/status` stays blocked (`403`). |
| Two-layer `507` exhaustion & rollback | Physical inode exhaustion, physical byte exhaustion, and logical 50 MB exhaustion each fail with HTTP `507 hosted_storage_quota_exceeded` and zero business DB rows committed; `4xx` releases held headroom while unexpected exceptions mark `unknown` until `reconcile_unknown()`. |
| Closed H05 readiness boundary | When `readiness()` returns `False`, business routes return `503` while authenticated `GET /api/hosted/settings` remains accessible and honestly reports `protection.state = "unavailable"`. |

H04.6 will implement Host Agent `AdmissionPort`, manual `epm-host-agent
provision` / retry orchestration, and offline synthetic seeding with pinned
`seed_bundle`.
