# OBS-001 — MVP observability

## Outcome and boundary

Proposed design, October 20, 2026. OBS-001 helps the product owner diagnose failures and measure adoption without turning a local property-management workspace into a behavioral data feed. The app remains fully usable offline and with reporting disabled. Local diagnostics and optional product reporting are separate switches and stores. This is operational telemetry, not the source-owned audit record; it never replaces audit, issue evidence, or command receipts.

The MVP has one operator per local workspace and no application user accounts. A cross-installation figure such as “how many users use Dark mode?” cannot be measured exactly. The supported figure is **active opt-in reporting installations by effective theme**, with the reporting-installation denominator, period, and unknown/non-reporting population stated. It is not a count of unique people or all installed copies. Hosted multi-operator analytics requires a later identity and consent design.

## Local diagnostics

Instrument the browser, API and scheduled local maintenance process at stable boundaries: startup/readiness, request errors, endpoint family and status class, command outcome, Home/query latency, backup/restore outcome and duration, and browser route load/error. Use a generated correlation ID across browser request, API operation and safe log entries; retain command idempotency/receipt identity only in its owning application record. Keep metric names and labels closed and low-cardinality. Do not use record IDs, paths, arbitrary route parameters, URLs, search terms, email addresses or exception messages as labels.

Local logs and timing records use a bounded ring/rotation policy with a documented default seven-day retention and size cap. Capture safe error codes, component, version, timestamp, duration and correlation ID; redact headers, request/response bodies, file names/paths, free text, credentials and source evidence. A diagnostic export in Settings lets the operator preview included categories and save a redacted package on explicit request. Export failure and storage-full states must not block business commands. No console or telemetry failure may change a domain transaction result. Accessibility and theme behavior remain owned by OPS-001/UI-001.

## Optional product reporting and theme metric

Settings → Privacy & diagnostics explains the exact allowlist and offers a separate **Share product usage** opt-in, off by default. Setup may configure a product-owner collector endpoint and provision a revocable per-installation upload credential in the operating-system credential store; neither the collector nor a credential is required to run EPM. Do not embed a shared write secret in the shipped app. The reporting identifier is a random machine-local pseudonym, is excluded from workspace backup, and is used only to replace that installation's latest state and deduplicate retries. Restore, move to another machine or missing credential requires fresh opt-in; it must not silently resume reporting. Turning reporting off stops usage uploads, drops queued reports and requests deletion of that identifier's retained state; retain only what is needed to retry deletion until acknowledged, and show a recoverable error if deletion cannot be confirmed.

The initial remote schema is closed: app version family, deployment class (`local`), coarse platform, reporting period, bounded success/error and latency buckets, and the **latest effective appearance** (`light` or `dark`) with `explicitly_selected` true/false. UI-001's effective default is Light even before a preference record exists; preserve that distinction. Send a current-state report on opt-in, on an actual preference change, and at most daily while active, rather than a clickstream. Never upload local diagnostic logs, traces, raw exceptions, correlation IDs, property or person data, AI inputs/outputs, source messages, file metadata, IP-derived location, or workspace ID. The collector should avoid storing request IPs in product analytics and apply short operational access-log retention separately. Network failure queues at most one replaceable state report, backs off, and never delays UI or API responses.

The collector accepts only authenticated, schema-versioned allowlisted reports; enforces size/rate limits; upserts by reporting ID with monotonic report version; and ignores exact retries. It exposes product-owner aggregate counts for installations seen in the last 30 days, split by current Light/Dark and default/explicit choice, plus total active reporting installations. It does not display a “user percentage” without that denominator and opt-in qualification. Inactive IDs age out after 30 days; aggregate history may retain only non-identifying period totals. Product-owner access to aggregates is separate from an operator's upload credential. An unavailable collector cannot affect local diagnostics or operator workflows.

## Ordered delivery

1. Define closed event/metric schemas, redaction tests, correlation propagation, retention/rotation, and a local diagnostic export. Measure instrumentation overhead and set a small fixed budget.
2. Add browser/API boundary timings and failures, plus local Settings status and export preview. Confirm normal, offline, storage-full and restart behavior without transmitting anything.
3. Add the consent/credential lifecycle and minimal collector with authenticated upsert, deletion, rate limits and aggregate query. Keep all outgoing payloads inspectable against the closed schema.
4. Add theme current-state reporting and the 30-day aggregate view. Verify Light default versus explicit Light, Dark selection, opt-out, restore and retry behavior before using the figures for product decisions.

## Validation matrix

| Area | Cases |
| --- | --- |
| Happy paths | Local error and latency diagnostics; explicit export; opt-in Light/Dark state updates and aggregate with denominator. |
| Invalid combinations | No collector/credential, denied consent, malformed/oversized event, unknown label, network outage, collector rejection, storage-full log rotation. |
| Idempotency/retry | Duplicate upload, out-of-order theme updates, retry after uncertain response, opt-out deletion retry; no double-counted installation. |
| Transaction rollback | Telemetry failure never rolls back or falsely confirms an owning business command; no report before a preference change commits. |
| Persistence/schema | Closed local/remote schemas, bounded retention, no sensitive payload in logs/export/network; latest theme plus explicit/default distinction. |
| Backup/restore | Workspace backup excludes reporting credential/ID and does not silently re-enable reporting on another machine; local diagnostics follow documented portability policy. |
| Query budget | Instrumentation adds no per-record source reads; bounded aggregate queries and negligible request/UI latency overhead. |
