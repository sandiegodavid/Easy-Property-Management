# HOA-002 — Deferred Association Management Design

## Purpose

`HOA-002` extends the narrow, event-driven HOA-001 records into standing association information and approval-request workflows without rewriting or losing HOA-001 notice and shared-repair history.

## Scope

- Association profiles and contacts; governing-rule/document records with source, effective/reviewed dates, and versioned files; property/association relationships; and manual architectural approval requests.
- Approval requests track submitted facts, evidence, response, status, and explicit outcome. They do not infer approval requirements, rule applicability, compliance, or deadlines.
- HOA assessments, board governance/meetings/voting, accounting, payment automation, and legal interpretation remain out of scope unless separately designed.

## Compatibility and migration

HOA-001 association/sender snapshots retain their historical values. HOA-002 may link a snapshot to a canonical association profile, but must not retroactively rewrite the notice, cited-rule text, evidence, status, closure, or shared-repair coordination record. New association documents are versioned, source-attributed, and never treated as app-authored legal conclusions.

## Design decisions required before implementation

1. Whether association profiles use shared Party identity directly or a dedicated association aggregate with a Party link.
2. Which approval categories and statuses are genuinely supported, and whether submissions are only prepared for manual operator sending.
3. Retention/access policy for governing documents and how the app distinguishes a copied document from an authoritative current version.
4. Whether assessments are merely recorded as contextual notice facts or become a separately owned financial capability.

## Definition of done

HOA-002 may begin only after those decisions are resolved and HOA-001 compatibility is tested. Its implementation must preserve existing notice/shared-repair identities and audit histories, offer no legal/compliance inference, and keep each new source document or approval outcome explicitly evidenced.
