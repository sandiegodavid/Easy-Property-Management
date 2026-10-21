# DATA-003 — Read-Only Google Sheets Intake Design

## Purpose

`DATA-003` adds a read-only Google Sheets source to the DATA-002 review/commit pipeline during new-workspace onboarding. It changes source acquisition only: mapping, validation, duplicate handling, confirmation, commit, audit, and outcomes remain DATA-002 contracts.

## Scope and boundaries

- Authorize only the least-privilege read scope needed to list/select a spreadsheet and retrieve selected worksheet values.
- The app never writes, publishes, shares, or continuously synchronizes source sheets.
- Google authorization is not an application account or standing connection. Temporary tokens stay in the local secure store, are excluded from workspaces/backups/exports, and are represented in the app only by masked status.
- DATA-003 owns the temporary authorization and secure-store credential lifecycle for this onboarding source. It does not add a generic third-party connector framework or mail/SMS access.

## Workflow

1. While onboarding a new workspace, the operator explicitly authorizes Google Sheets and sees the requested read-only scope and disclosure.
2. Select a spreadsheet and worksheet from authorized resources.
3. Read values into a DATA-002 immutable snapshot with source spreadsheet ID, sheet ID/name, range/header metadata, retrieval instant, connector identity, and normalized-value digest.
4. Disconnect temporary authorization when source acquisition is completed or canceled. Continue through DATA-002 mapping, validation, review, confirmation, and outcomes using the captured snapshot without a live Google connection. A retry that needs another fetch requires fresh authorization within onboarding.

The confirmation request names the snapshot digest/revision. If the source changes after preview, the app still imports exactly the reviewed snapshot. A fresh fetch requires a new preview and invalidates no previous audit record.

## Connection lifecycle

The onboarding source-acquisition session shows Not authorized, Authorizing, Ready to capture, Needs reauthorization, and Disconnected, each with a truthful reason and recovery action. Completion, cancellation, or explicit revoke removes the local credential reference and prevents future reads; it does not erase captured DATA-002 snapshots/outcomes. A restored workspace never resumes an authorization session from backup. After onboarding, Google Sheets is not presented as an active connection.

## Verification and definition of done

Test authorization denial, expired/revoked credentials, narrow source selection, read-only scope, snapshot stability after remote edits, no source writes, restore behavior, and DATA-002 duplicate/retry guarantees. DATA-003 is complete when a selected Sheet becomes a verified, immutable DATA-002 source snapshot with no ongoing sync or source mutation.
