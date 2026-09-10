# VEND-002 — Provider Reputation Links

## Purpose

`VEND-002` lets the operator retain a small, manually curated record of where a saved provider's public reputation can be reviewed. It adds reputation links for Google, Yelp, Angi, and named other sources, with private operator notes and the date the operator last checked the link.

The feature is a local reference directory, not a review-platform integration. It helps the operator assess a saved provider while keeping selection human-controlled. `VEND-004` later owns live source connections, imported ratings or reviews, refresh/monitoring behavior, and credentials. `VEND-005` owns external provider discovery. Neither is pulled into this slice.

## Scope

VEND-002 provides:

- Multiple lifecycle-managed reputation links for one active or archived provider profile.
- Source types `google`, `yelp`, `angi`, and `other`; an `other` source has a required operator-defined source name.
- A required, canonical HTTPS URL, optional bounded operator notes, and an optional `last_checked_on` local date.
- Create, read through provider detail, patch, archive, and restore workflows.
- Correlated, append-only audit events; contextual privacy presentation; exact-schema validation; and encrypted backup/export/restore coverage.

VEND-002 does not provide:

- Ratings, review counts, review text, ranking, sentiment, verification, or any assertion that a link works or represents the provider accurately.
- External HTTP requests, browser automation, scraping, API tokens, OAuth, credentials, background jobs, polling, monitoring, or notifications.
- Provider discovery, shortlist import, quote requests, provider assignment, or automatic provider recommendations.
- A React provider directory screen. The API is ready for the deferred provider UI workflow; it does not expand UI scope.

## Core decisions

### A link is an operator-recorded pointer, not imported reputation data

The operator records a link they consider relevant and may add private context in `notes`. `last_checked_on` means only that the operator last reviewed the link on that date; it does not certify a rating, provider identity, source content, or current availability.

The application never fetches a URL during validation, reads its contents, sends a provider's information to a third party, or stores third-party credentials. A link may become stale, disappear, or redirect without changing local data. The operator may update its URL or archive it.

### Source identity is explicit and normalized

Known sources use a fixed source kind:

- `google`
- `yelp`
- `angi`

For `other`, the operator supplies a trimmed 1–80 character `source_name` such as `Better Business Bureau` or `Nextdoor`. The application stores a normalized `source_key`: the source kind for a known source, or the NFKC-trimmed, case-folded source name for `other`.

An active provider has at most one link for a source key and at most one link for a normalized URL. This prevents accidental duplicate records without treating two different platforms as the same source. Archiving a link releases its active uniqueness keys while retaining history.

### URLs are stored in a safe, stable local form

VEND-002 accepts only absolute `https` URLs with a host, no user information, and no fragment. The display URL is normalized for storage by lowercasing the scheme and host, removing a default port, and removing a fragment; the path and query remain intact. The normalized URL is used for duplicate detection and is not used to contact the source.

The URL is bounded to 2,048 characters after normalization. The contract intentionally does not guess a source from the host or rewrite tracking/query parameters, because that could silently alter an operator's intended reference.

### A later live integration extends, rather than replaces, local records

`VEND-004` must keep external connection configuration and credentials outside the workspace, keyed to the workspace through the existing secret-store boundary. It may associate imported snapshots with a VEND-002 link, but it must not overwrite the operator's URL, notes, source selection, or last-checked date without an explicit audited operator action.

## Data model

All IDs are UUIDs. Timestamps are timezone-aware UTC text. `last_checked_on` is an ISO local date and cannot be later than the operator's current local date. The table is part of the current greenfield Alembic baseline and the current-format schema—not a compatibility migration.

### `provider_reputation_links`

| Field | Rule |
| --- | --- |
| `id` | Stable UUID primary key. |
| `party_id` | Required foreign key to `provider_profiles.party_id`. |
| `source_kind` | Required `google`, `yelp`, `angi`, or `other`. |
| `source_name` | `NULL` for known sources; required trimmed display name for `other`. |
| `normalized_source_key` | Required normalized source identity used for active uniqueness. |
| `url` | Required canonical HTTPS display URL, maximum 2,048 characters. |
| `normalized_url` | Required canonical lookup URL, maximum 2,048 characters. |
| `notes` | Optional trimmed operator context, maximum 4,000 characters. |
| `last_checked_on` | Optional ISO local date. Future dates are rejected by the application command. |
| `created_at`, `updated_at`, `archived_at` | UTC lifecycle timestamps. |

Database constraints require a valid source-kind vocabulary, the correct `source_name` nullability for known versus other sources, and nonblank source keys and URLs. Partial unique indexes enforce active `(party_id, normalized_source_key)` and active `(party_id, normalized_url)` uniqueness. The exact schema validator verifies columns, types, nullability, foreign keys, constraints, index columns, uniqueness, and partial predicates.

## Workflows and invariants

### Add a reputation link

The provider profile must exist and be active. The application validates and canonicalizes the command, rejects an active duplicate source or URL with a controlled `409`, inserts the link, and appends a `provider_reputation_link` `created` event in one immediate transaction and one correlation ID.

The provider may have no links. Adding a link does not affect `preferred`, `neutral`, or `avoid` selection state. It does not imply endorsement.

### Edit, archive, and restore

PATCH can change source, URL, notes, and last-checked date. It revalidates all fields and active uniqueness before persisting a complete before/after audit event. An empty PATCH is a no-op: it does not update timestamps or create an event.

Archiving requires explicit confirmation and is rejected when already archived. Restoration requires the parent provider profile and shared party to be active, rechecks active uniqueness, and rejects a conflict rather than overwriting another link. No workflow physically deletes a link.

Provider-profile archive retains its links as history but removes the profile from ordinary provider search. Profile restore does not automatically restore individually archived links.

### Read and search behavior

Provider detail returns active reputation links by default and includes archived links only with its existing `includeArchived=true` option. Link order is stable: source display/name followed by creation ID. Provider list summaries add only `reputationLinkCount`; they do not expose URLs or notes.

VEND-002 does not add reputation filters to provider search. `VEND-004`, `VEND-005`, or a future provider UI search design may introduce explicit search/filter behavior after the query needs are known.

## API contract

All routes require a ready workspace. Mutations require the workspace writer lock. Requests use `extra="forbid"`; confirmation uses `StrictBool`; dates use typed ISO dates; application commands independently revalidate direct callers. Responses use explicit Pydantic models.

| Method | Path | Intent |
| --- | --- | --- |
| `POST` | `/api/providers/{partyId}/reputation-links` | Add one manual reputation link. |
| `PATCH` | `/api/providers/{partyId}/reputation-links/{linkId}` | Partially update one active link. Omitted fields retain their values; nullable `notes` and `lastCheckedOn` may be explicitly cleared. |
| `POST` | `/api/providers/{partyId}/reputation-links/{linkId}/archive` | Archive one link after `{"confirmed": true}`. |
| `POST` | `/api/providers/{partyId}/reputation-links/{linkId}/restore` | Restore one archived link when parent availability and uniqueness allow it. |

`GET /api/providers/{partyId}` includes `reputationLinks`; `GET /api/providers/{partyId}?includeArchived=true` includes both active and archived records. `GET /api/providers` adds `reputationLinkCount` to each summary.

Malformed request shapes, invalid URL/date/source values, and unknown fields return `422` at the HTTP boundary; command violations return controlled `400`; missing provider or link records return `404`; lifecycle, duplicate, and concurrent-write conflicts return `409`.

## Audit, privacy, and portability

Every mutation records a `provider_reputation_link` event with normalized source and URL values sufficient to explain identity/uniqueness. General activity presentation exposes the source kind, lifecycle state, and last-checked date, but redacts `url`, `normalizedUrl`, and `notes`; URLs can contain account, location, or tracking identifiers. Contextual provider history may show the full record to the local operator.

All policies are registered before a mutation can write events. The link rows and audit history are included in encrypted backup, export, and restore. VEND-002 stores no fetched review content, remote objects, credentials, access tokens, or secrets, so the existing archive secret-exclusion policy remains sufficient.

## Implementation outline

1. Add the SQLAlchemy model, current greenfield baseline table/partial indexes, module-owned exact schema validator, and product schema/backup allowlist updates.
2. Add domain models plus validated create/patch commands for source, canonical URL, date, notes, lifecycle, and explicit `UNSET` handling.
3. Extend the provider unit-of-work protocol and SQLite adapter with bounded detail/list projections and immediate transactional mutations. Keep SQLAlchemy imports out of provider application services.
4. Add explicit provider-service workflows and correlated audit writes; register a source-aware reputation-link presentation policy at composition.
5. Extend typed provider responses and routes. Preserve the existing party/provider boundaries and role-guard behavior.
6. Add regression coverage for canonicalization, source rules, URL/source uniqueness, patch clearing/no-op behavior, lifecycle conflicts, audit redaction/correlation, schema rejection, and encrypted backup/export/restore.

## Acceptance criteria

VEND-002 is complete when:

1. An active provider can retain, edit, archive, and restore manual Google, Yelp, Angi, and named-other reputation links without duplicate active source or URL records.
2. URLs, source names, dates, and notes are validated by both typed HTTP inputs and application commands; no external requests occur.
3. Provider detail and summary expose the documented typed reputation representations without leaking URLs or notes in generalized activity.
4. Every link mutation and its audit event commit atomically with one correlation ID; archive/restore preserves history and enforces parent/lifecycle/uniqueness rules.
5. Current-format schema validation rejects incomplete or weakened reputation-link schema/index definitions.
6. Encrypted backup, export, and restore preserve links and audit history without credentials or remote review data.
7. VEND-002 leaves categories, external monitoring, discovery, quotes, assignments, ratings, review ingestion, and automatic recommendations to their owning backlog items.

## Dependencies and follow-on work

VEND-002 requires completed `VEND-001`, `AUDIT-001`, `LOCAL-001`, and `LOCAL-002`. It does not add a dependency on FILE-001 because reputation links are URL metadata, not local attachments.

`VEND-004` depends on VEND-002 to add live reputation-source integrations and monitoring. `ISSUE-AI-004` and `AI-REC-002` may use locally recorded source/last-checked context only as an explainable advisory signal, never to contact, assign, or automatically select a provider. `VEND-CAT-001`, `MAINT-002`, and `MAINT-003` remain separate owners of category, selection, and work-history concerns.
