# DATA-003 — Read-Only Google Sheets Intake Design

## Purpose

`DATA-003` adds a read-only Google Sheets source to the DATA-002 review/commit pipeline. It changes source acquisition only: mapping, validation, duplicate handling, confirmation, commit, audit, and outcomes remain DATA-002 contracts.

## Scope and boundaries

- Authorize only the least-privilege read scope needed to list/select a spreadsheet and retrieve selected worksheet values.
- The app never writes, publishes, shares, or continuously synchronizes source sheets.
- Google authorization is not an application account. Tokens stay in the local secure store, are excluded from workspaces/backups/exports, and are represented in the app only by masked status.
- DATA-003 does not add a generic third-party connector framework; CONN-001 supplies the required secure connection foundation.

## Workflow

1. The operator explicitly connects Google Sheets and sees the requested read-only scope and disclosure.
2. Select a spreadsheet and worksheet from authorized resources.
3. Read values into a DATA-002 immutable snapshot with source spreadsheet ID, sheet ID/name, range/header metadata, retrieval instant, connector identity, and normalized-value digest.
4. Continue through DATA-002 mapping, validation, review, confirmation, and outcomes.

The confirmation request names the snapshot digest/revision. If the source changes after preview, the app still imports exactly the reviewed snapshot. A fresh fetch requires a new preview and invalidates no previous audit record.

## Connection lifecycle

States are Not configured, Setup required, Ready, Paused, Needs attention, and Revoked, each with a truthful reason and recovery action. Revoke deletes the local credential reference and prevents future reads; it does not erase historical DATA-002 snapshots/outcomes. Restore of a workspace has Setup required because credentials are external to workspace data.

## Verification and definition of done

Test authorization denial, expired/revoked credentials, narrow source selection, read-only scope, snapshot stability after remote edits, no source writes, restore behavior, and DATA-002 duplicate/retry guarantees. DATA-003 is complete when a selected Sheet becomes a verified, immutable DATA-002 source snapshot with no ongoing sync or source mutation.
