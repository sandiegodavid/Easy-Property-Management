# Current frontend architecture

## Layout and implemented surfaces

[apps/web](../../application/apps/web) is the React/Vite/TypeScript application; [packages/ui](../../application/packages/ui) supplies shared components/tokens; [packages/contracts](../../application/packages/contracts) supplies generated OpenAPI types/client transport. One npm workspace/lockfile governs them.

The current source contains bootstrap/readiness, configurable navigation/light-dark preferences, shared disclosures/async regions, recovery transport, contextual Property/Owner reads, Portfolio/Party/Tenant/Provider forms, and Lease/Inspection workflows. Money, Maintenance/communications/Tasks/owner concerns, search/coverage browser workflows, production AI controls and final Home/integration acceptance remain in [active UI delivery](../active/UI-001_IMPLEMENTATION_MATRIX.md). A route or backend capability alone does not prove that workflow is delivered.

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

Run lint, format and type checking for frontend changes; add focused browser proof for enabled source read/write/recovery paths. Fixtures help presentation but do not prove persistence. Active delivery owns the remaining theme/narrow-layout/accessibility/restart/restore integration acceptance.
