# OPS-001 — Operator Support Design

## Purpose

`OPS-001` supplies the bounded, operator-facing compositions and durable preferences that UI-001 needs without moving domain authority into the browser. It owns workspace bootstrap, navigation/appearance preferences, property and owner directory/overview reads, global search, coverage/review provenance, and recovery for incomplete short forms.

## Boundaries

- Source modules remain authoritative for property, owner, lease, money, maintenance, communication, and task facts. OPS-001 composes their application ports only; it never imports their persistence adapters or issues per-row reads.
- Domain drafts (lease, inspection, settlement, and similar) remain source-owned. OPS-001 is only for incomplete browser-form recovery where no domain draft exists.
- Owner statements, fees, balances, and disbursements remain respectively OWNER-001/005/002 work. An overview reports available source facts, never an inferred owner entitlement.
- No React implementation is part of OPS-001.

## Bootstrap and preferences

`GET /api/operator/bootstrap` returns one bounded response: workspace readiness and identity, write capability, recovery actions, enabled capability IDs, preference revision, navigation preference, appearance preference, and a contract version. A non-ready workspace returns an explicit `unavailable` or `busy` state with only backend-supported recovery actions; it is never represented as an empty portfolio.

Persist one versioned workspace preference record:

| Field | Rule |
| --- | --- |
| `appearance` | `light` or `dark`. |
| `destination_order` | Valid permanent destination IDs, each at most once. |
| `hidden_destination_ids` | Hideable IDs only; Home and Settings cannot be hidden. |
| `revision` | Required optimistic-concurrency revision. |

`PUT /api/operator/preferences` validates IDs and revision atomically. Hidden destinations remain discoverable under More and never hide unresolved work from DASH-001.

## Directory, overview, and search reads

Provide set-based, cursor-paginated reads with matching totals, stable ID tie-breaks, `asOf`, and availability/provenance per section:

- `GET /api/operator/properties`: recognition identity, ownership context, occupancy/availability, attention state, applicable coverage summary, and explicit filter values. Search supports address, tenant, and owner text.
- `GET /api/operator/properties/{id}/overview`: identity, occupancy, owners, current lease, available money summary, next actions, coverage, and contextual routes. It does not claim unavailable information is zero.
- `GET /api/operator/owners` and `/owners/{id}/overview`: owner identity, related property summaries, actionable records, conversation/lease/maintenance summaries, and only available money facts, each labeled with provenance.
- `GET /api/operator/search`: bounded grouped results with source type/ID, label, context, archived marker, destination route, stable cursor, and exact query echo. Results from hidden destinations remain eligible; archived records require an explicit include option.

Every cross-module call is through a consumer-neutral application read port and is batched by IDs. A section may be `available`, `stale`, or `unavailable`; one failed section cannot erase successful sections.

## Coverage and review provenance

Persist or compose an explicit coverage result per supported area: `area`, `applicability`, `state`, `cause`, source/evidence revision, `lastManualReviewAt`, `trigger`, and `resolutionRoute`. States are Recorded, Needs review, Missing required information, and Not applicable.

The initial supported areas are occupancy/availability, lease, rent, deposit, and maintenance. Triggers are relevant source changes or an explicit review date; a generic row update timestamp is insufficient. Manual review records actor, timestamp, basis, and the source revision reviewed. Not applicable requires an allowed reason and never bypasses required data. Coverage is operational visibility, not legal or physical-property compliance certification.

## Incomplete-form recovery

Persist a versioned recovery record only after an acknowledged autosave: workflow/form key, related source identity, schema version, payload, revision, saved timestamp, and expiry policy. It excludes credentials, raw file bytes, and official domain state. APIs support list/load/update/discard with optimistic concurrency. A schema mismatch is recoverable but cannot silently replay an incompatible payload.

The browser distinguishes dirty, saving, saved, failed, and conflicted. It must not claim a local draft is official; substantive domain drafts use their source contract instead.

## Verification and definition of done

Verify bounded query counts for populated directories/overviews, matching totals and cursors, no per-row fan-out, `asOf` consistency, partial availability, tenant/owner/address search, owner-history preservation, preference conflicts, coverage trigger/review history, and restart/form-conflict recovery. OPS-001 is complete when these typed APIs and audited mutable records are implemented without browser-side domain derivation.
