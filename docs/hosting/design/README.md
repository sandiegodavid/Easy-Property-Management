# Hosted MVP Design (`HOSTED-001`)

For the live Pilot 0 (`H01–H06`) architecture and accepted decisions, see [../ARCHITECTURE.md](../ARCHITECTURE.md). For operational procedures, see [../operations/README.md](../operations/README.md).

This folder holds the **accepted HOSTED-001 specification** governing both live platform invariants and future `H07–H12` slices:

- [HOSTED_MVP_DESIGN.md](HOSTED_MVP_DESIGN.md) — Master navigation index and deep-link anchor map for the 11 focused specification guides under [`mvp/`](mvp/delivery-plan.md).
- [mvp/delivery-plan.md](mvp/delivery-plan.md) — Pilot 0 operating rules and `H07–H12` roadmap (automated provisioning, Paid 1/2 sizing & 15-min RPO, Stripe billing, per-operator release scheduling, Free idle suspension/wake, and 100-operator qualification).
- [mvp/subscriptions-storage-and-runtime.md](mvp/subscriptions-storage-and-runtime.md) — Logical/physical storage admission, Paid 1/2 sizing protocol (`H08`), Stripe lifecycle (`H09`), and Free idle/wake (`H11`).
- [mvp/releases.md](mvp/releases.md) — Independent component releases, per-operator update scheduling (`H10`), and post-Pilot 0 SQLite schema upgrade principles.
- [SQLite schema upgrade workflow](../research/SQLITE_SCHEMA_UPGRADE_WORKFLOW_2026-10-31.md) — Accepted H10 per-operator SQLite schema upgrade workflow, release-history freezing, transactional DDL rebuilds, and qualification matrix.
- [mvp/implementation-contracts.md](mvp/implementation-contracts.md) — 6-store schema ownership map (`H07–H11` additions) and post-Pilot 0 forward-only schema evolution contract.
- [Pilot 0 capacity snapshot refresh](pilot0-capacity-refresh.md) — proposed host timer, publication safeguards, and validation.
