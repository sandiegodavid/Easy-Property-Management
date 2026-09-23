# Synthetic demo workspace data

`synthetic-demo-data.json` is a portable, fully synthetic dataset for product demos,
UI development, and manual acceptance checks. It deliberately contains no live
operator information, credentials, attachments, or SQLite database.

The snapshot is set on **September 23, 2026** and mirrors the scenarios in the
UI-001 operator-experience prototype:

- a repair that needs a decision, an overdue partial rent payment, and an owner
  report awaiting verification;
- waiting and upcoming follow-ups, appointments, and a deposit settlement;
- occupied, vacant, client-owned, and self-owned properties;
- owner, tenant, provider, lease, money, maintenance, conversation, legal, and
  HOA-notice records connected with stable synthetic IDs.

All monetary amounts are USD minor units. Dates without a time are property-local
dates; timestamps are UTC ISO-8601 values. The file is a seed fixture, not a
current-format application workspace: a future importer or seed command must map
its records through the application's APIs and audit rules instead of copying it
into a live database.
