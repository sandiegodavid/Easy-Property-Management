# H04.10 exit review and H04/H05 handoff (2026-11-22)

Reviewed November 22, 2026, following completion of all H04 implementation slices (**H04.1–H04.10**) and native Linux/GCP qualification on `epm-h02-host` (`project-47b72bb7-ba90-42c9-910`, `us-west1-b`, Linux `7.0.0-1017-gcp`, `x86_64`). **H04 ("Admin-lite and Free usage") is complete and ready for H05 handoff.**

- H04 Design: [HOSTED_MVP_H04_DESIGN.md](../../design/HOSTED_MVP_H04_DESIGN.md)
- H04.9 Free Physical Sizing Report: [HOSTED_MVP_H04_9_FREE_SIZING.json](HOSTED_MVP_H04_9_FREE_SIZING.json) (`sha256: a8662dfb000974771d7a591281ee60fbb35796e01c09b208ccd624b5cb2e13ff`)
- H04.9 Native Evidence: [HOSTED_MVP_H04_9_EVIDENCE.json](HOSTED_MVP_H04_9_EVIDENCE.json)
- H04.10 Native GCP Handoff Report: [HOSTED_MVP_H04_10_HANDOFF.json](HOSTED_MVP_H04_10_HANDOFF.json)
- H04.10 Checkpoint: [HOSTED_MVP_H04_10_CHECKPOINT.md](../../design/HOSTED_MVP_H04_10_CHECKPOINT.md)

---

## Verified H04/H05 Handoff Gates (GCP Native)

| Gate | Scope & Result |
| --- | --- |
| Two disposable Operator assignments (`gcp_native`) | Provisioned `h04-empty` (`initial_data="empty"`, `observed_usage_bytes: 2,088,960`) and `h04-synth` (`initial_data="synthetic"`, pinned `synthetic-demo-v1:2ad5ca6acec28823a2988c77e3c81e0bfc2bec61d43839db8e1324b73761aa5a`, `observed_usage_bytes: 3,698,688`) through `AdminControlService` -> `AdminEffectAdmission` -> `ManualProvisioner` with real ext4 `prjquota` ceilings from H04.9 (`workspace: 162 MiB / 5,376 inodes`, `control: 18 MiB / 768 inodes`, `scratch: 33 MiB / 768 inodes`). Idempotent retry succeeded for both without duplicating state. |
| Missing H05 protection holds both workspaces closed | Both assignments reached `setup_state="ready_for_claim"` with `desired_access="enabled"`, `effective_access_cached="disabled"`, `protection_state="unavailable"`, and `readiness_protection_gate="unavailable"`. `ManagedBusiness.capabilities()` returned `[]` when `readiness()` is `False`. |
| Gateway projection (`auth_projection.auth_config`) | `SharedIdentityManifest` `v2` projected all 11 `ADMIN_LITE_ROUTES` (+ `/`) on `https://admin.epmdemo.xyz`. Both disposable operators projected strictly `held` `AuthRouteManifest` routes (`/auth/start`, `/auth/complete`, `/auth/status`) with zero business reverse-proxy routes. Requesting `desired_state="eligible"` was rejected (`HostAgentUnavailable`) for both `h04-empty` and `h04-synth`. |
| Admin-lite & invitation boundaries | `ReissueInvitation` was rejected (`AdminConflictError`) while `setup_state="pending"`, succeeded once `ready_for_claim`, confirmed delivery (`pending_delivery -> sent`), and leaked zero raw invitation tokens in `AdminDetail`. `RefreshSource` populated cached `operator_source_observations` for set-based `AdminList` (`list_count: 2`) and `AdminDetail`. |
| Operator Settings & Free pilot honesty | `GET /api/hosted/settings` returned HTTP `200` with `plan_code="free"`, `usable_bytes=50,000,000`, `used_bytes=3,698,688`, `protection_state="unavailable"`, `support_contact="support@epmdemo.xyz"`, and zero paid-upgrade controls. |
| Production host-agent findings fixed during H04.10 | Removed `httpx`/`TestClient` dependency from `synthetic_seed.py` (replaced with zero-`httpx` `_OfflineAsgiClient`) and deferred `LocalApiClient` import in `demo/seed.py` to `main()`; synchronized `TZ="America/Los_Angeles"` during offline synthetic seeding so `leases` (`date.today()`) and `portfolio` (`ZoneInfo`) agree on UTC Linux hosts. |
| Disposable cleanup | Both disposable operator directory trees, ext4 `prjquota` fixture roots, and disposable system accounts (`epm-h410-*`) were removed (`disposable_operators_removed: true`) and `epm-h02-host` was stopped. |

---

## Handoff to H05

H04 leaves all H05-owned gates strictly closed and unfabricated:
- `protection.state` remains `"unavailable"` in both Admin-lite (`AdminDetail`, `AdminList`) and Operator Settings (`GET /api/hosted/settings`).
- `Gateway` continues rejecting `desired_state="eligible"` until H05 supplies the verified recovery-point gate and jointly qualifies the positive workspace-session / eligible-claim / recovery step-up path.
- `h05_backup_restore_reserve` remains `"deferred_to_H05"` in [HOSTED_MVP_H04_9_FREE_SIZING.json](HOSTED_MVP_H04_9_FREE_SIZING.json) for H05 to measure backup/restore staging reserves independently.
