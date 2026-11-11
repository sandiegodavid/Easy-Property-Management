# admin-recovery schema resources

**Scaffold only — unavailable for initialization or upgrade.** Delivery owner: H05.
Private Admin recovery authority, independent of the main Admin store.

This directory owns its `alembic.ini`, environment and future `versions/` revisions.
Revision namespace: `admin_recovery_`. No baseline, destination, default connection URL,
identity, policy, release assignment or session is supplied. The environment rejects
upgrade/stamp (including offline SQL) before using a connection or creating a file.
An empty revision listing is not schema readiness.

Use the [shared resource and initialization contract](../README.md) for discovery,
runner ownership, failure behavior and component packaging requirements. The
[owning dictionary](../../../docs/database/admin-recovery.md) owns table/column definitions.
The existing business and hosted-demo consumers are not wired to this scaffold.
