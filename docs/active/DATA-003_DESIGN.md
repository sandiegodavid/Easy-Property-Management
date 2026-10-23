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

## Included operator interface delivery

This UI is part of this functional backlog and its completion criteria. Reuse the delivered UI-001 shell, generated contracts, source-owned commands, Light/Dark themes, keyboard/focus behavior and recovery patterns. Validate real temporary-workspace reads/writes, stale revisions, lost responses, restart/restore and bounded queries; backend-only delivery is incomplete.

#### D44: Support Excel uploads and direct read-only Google Sheets import

Support local Excel uploads and, during new-workspace onboarding, direct Google Sheets selection through temporary read-only authorization. Let the operator select the spreadsheet and worksheet and review a captured source snapshot before import. Import exactly the reviewed snapshot; rereading changed source values requires a new preview and fresh authorization if the prior session ended. Disconnect after source acquisition completes or is canceled; mapping, review and commit use the captured snapshot. Do not require a sheet to be published publicly, modify the source sheet, or introduce ongoing synchronization in MVP. Source authorization does not create an application user account; credentials follow existing local secure-storage boundaries.

Own the onboarding Sheets authorization, spreadsheet/worksheet picker, acquisition progress, cancel/revoke and reauthorization UI. Hand the frozen snapshot to DATA-002’s shared review. Show authorization state independently of snapshot/import state. Test changing the remote sheet after capture: import exactly the reviewed snapshot or require a new preview; never silently refresh it.
