# Current frontend architecture

## Layout and implemented surfaces

[apps/web](../../application/apps/web) is the React/Vite/TypeScript application; [packages/ui](../../application/packages/ui) supplies shared components/tokens; [packages/contracts](../../application/packages/contracts) supplies generated OpenAPI types/client transport. One npm workspace/lockfile governs them.

The browser delivers Portfolio/identity/Provider, Lease/Inspection, Money/reporting, Maintenance, manual communications, Tasks/waiting, owner concerns, search/coverage, AI-governance controls and manual Intake. [Workflow guide](workflows.md) maps their source authority and code. Home uses independent full-summary/live-attention queries, capture-bound source pages, visible transition/minute refresh and source-owned commands; completed acceptance is recorded in [DASH-001](../archive/designs/DASH-001_DESIGN_COMPLETED_2026-10-14.md). Production AI capabilities require owning registrations; [UI-002](../active/UI-002_DESIGN_preliminary.md) retains its deferred workflows.

Implementation uses `src/app` for routing/bootstrap, `src/shared` for contextual reads, search/coverage and recovery, and `src/workflows` for source forms/records. It does not use the earlier proposed per-feature folder tree. React Router, TanStack Query and React Hook Form separate navigation, remote facts and editable input. Generated contract files are replaced reproducibly, never hand-edited.

## Bootstrap, routes and context

[workspace-gate.tsx](../../application/apps/web/src/app/workspace-gate.tsx) gates children on typed bootstrap. [workspace-scope.ts](../../application/apps/web/src/app/workspace-scope.ts) separates workspace/runtime query identities. Busy/missing/invalid/unsupported workspace and connection errors are distinct. No failed load becomes an empty directory.

[destinations.ts](../../application/apps/web/src/app/destinations.ts) defines permanent destinations and allowed Property/Owner child sections. Home and Settings stay fixed; hidden available destinations remain under More/context. Typed IDs/sections map to canonical paths; source targets are not arbitrary URLs. Appearance/navigation persist through revision-safe Operator preferences.

## State ownership

Server/query state carries current records, revisions, availability, counts/cursors and source freshness. React Hook Form owns editable input. Shared recoverable-form hooks coordinate acknowledged autosave and attempts; route/expansion state does not become domain state. Never recompute authoritative money/status/coverage in browser code.

[mutations.ts](../../application/apps/web/src/shared/mutations.ts), [recovery.ts](../../application/apps/web/src/shared/recovery.ts) and [use-recoverable-form.tsx](../../application/apps/web/src/shared/use-recoverable-form.tsx) preserve the canonical request/key, prepare through OPS and dispatch to the owning domain. They normalize typed errors, serialize saves and prevent duplicate/automatic consequential retries. Conflict keeps edits for explicit source review; unknown outcome reconciles the original key.

Saved recovery is incomplete input, not an official draft. Byte evidence retains normalized metadata/hash and requires matching file reselection. Source-owned drafts use their domain APIs. Navigation guards account for dirty/unknown state and context identity.

## Interaction system

The entire non-editable summary bar is one accessible disclosure control. Click/keyboard activation toggles details below; inputs/buttons belong inside the expanded body. Preserve independent expansion and input when collapsed, and pause hidden work where the feature owns fetching/polling. Visible guidance explains toggling.

Shared async regions distinguish loading, successful empty, unavailable, partial and retained stale results with original timestamps. Directories use server totals/cursors; section errors preserve other sections. Labeled fields, error summaries, confirmations, semantic tables, focus and announcements are shared primitives rather than domain policy.

## Build and local delivery

Browser API calls use relative `/api`; Vite's explicit loopback dev origin proxies to local FastAPI. `npm run package:web` stages trusted compiled assets into the Python wheel. Entry HTML is not cached; fingerprint assets are immutable. Restricted SPA serving and CSP keep API/errors/assets distinct. See [local security](../platform/security-and-audit.md).

## Validation entry points

- [Packaged browser tests](../../application/apps/web/tests).
- [Shared component/recovery fixtures](../../application/apps/web/component-tests).
- [Frontend quality policy](../CODE_QUALITY.md).
- [Generated contracts](../../application/packages/contracts).

Run lint, format and type checking for frontend changes; add focused browser proof for enabled source read/write/recovery paths. Fixtures help presentation but do not prove persistence. Recorded UI-001 acceptance covers themes, narrow layouts, accessibility, process restart and encrypted restore; see [validation](validation.md). These historical results are not a fresh test run.

## Routing and read contracts

The route registry and [main.tsx](../../application/apps/web/src/main.tsx) are the source of exact implemented routes; typed context targets explicitly allow Property/Owner child sections. Main navigation clears contextual scope, while source links carry visible filters. URL state holds search, period, scope, archived visibility and collection continuation; changing filters resets cursors. 409 restart preserves criteria. Server exact totals and independent section availability must not be rebuilt from browser page rows.

Bootstrap is a bounded typed read even when domain routes are gated, with nullable preferences and explicit recovery/setup guidance. A busy single-writer workspace is a gate, not an implicit read-only session. Runtime identity cancels obsolete requests/caches and isolates saved forms to their workspace. Transport failure is distinct from reported workspace unavailability.

Source forms obtain current owning records and independent child/Space/ledger revisions where required. Read-only ID/key receipt lookup recovers the exact original outcome even after later edits or child deletion. Only the current explicit OPS registry can prepare recoverable attempts; a UUID field alone is insufficient. Internal File reuse/storage validation and system Intake transitions retain consumer/source authority rather than becoming standalone operator forms. Never hardcode historical registry counts into feature eligibility.

## Errors, privacy and shared presentation

Shared mutation normalization handles structured and legacy HTTP detail values; components do not parse raw errors separately. Validation/oversized errors preserve input; missing records offer context-preserving return; stale conflicts require explicit current-source review; lost responses retain the original key. Automatic consequential retries are prohibited. Source mutation results update/invalidate affected query families; refresh does not overwrite dirty form values.

Shared components under [packages/ui/src](../../application/packages/ui/src) provide semantic tables/directories, disclosure, forms/dialogs, availability and attention/calendar presentation. Styles use semantic tokens from `tokens.css` and `components.css`; document theme changes do not remount editable workflows. Route and contextual record components own domain interpretation. Supported reflow/keyboard/contrast behavior has executable proof in the validation guide.

Local Host/Origin policy also guards multipart uploads; the browser uses relative API calls and never sends the CLI intent marker. Workspace files are read through Files APIs, text is rendered safely, and secrets/file bytes/raw evidence are excluded from OPS recovery and browser storage. Error telemetry retains safe correlation identifiers rather than payloads, stack traces or private workspace paths.
