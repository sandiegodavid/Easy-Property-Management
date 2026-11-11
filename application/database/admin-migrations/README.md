# admin schema resources

**Scaffold only — unavailable for initialization or upgrade.** Structural delivery
owner: H02, for the complete Pilot 0 main-Admin baseline/FK closure. H02 initializes
protected deployment metadata only. H03/H04 retain identity/Free-policy/operator
population and behavior; H05 owns workspace protection observations. Candidate
builds do not seed qualified releases or production assignments.

This directory owns its `alembic.ini`, environment and future `versions/` revisions.
Revision namespace: `admin_`. No baseline, destination, default connection URL,
identity, policy, release assignment or session is supplied. The environment rejects
upgrade/stamp (including offline SQL) before using a connection or creating a file.
An empty revision listing is not schema readiness.

Use the [shared resource and initialization contract](../README.md) for discovery,
runner ownership, failure behavior and component packaging requirements. The
[owning dictionary](../../../docs/database/admin-registry.md) owns table/column definitions.
The existing business and hosted-demo consumers are not wired to this scaffold.
