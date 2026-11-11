# host-inventory schema resources

H02.2 delivers `host_inventory_0001_initial`: Complete six-table protected host inventory baseline, including principals, ingress and child-effect receipts.
All DDL lives in the owning revision and [shared column conventions](../hosted_ddl.py).
No identity, policy, operator, release assignment or session is seeded by schema creation.

Use `resource_config(HostedStore, application_directory=...)` for installed-resource
discovery and `app.platform.hosted_schema.initialize_store(...)` for exclusive fresh
initialization or exact read-only reinit. There is no default connection URL.
Direct Alembic upgrade/stamp/ensure-version/offline commands reject; only the owning
runner supplies the explicit SQLite transaction. No migration or downgrade path.

The installed set consists of `alembic.ini`, `env.py`, this revision and the shared
`database/hosted_ddl.py` helper. H02.4 must package them together and verify installation
outside the checkout; current wheel staging is not yet hosted-image qualification.
Recovery/access resources remain independently unavailable until their owners deliver them.

Protected metadata binding is separate from schema initialization. Main Admin may
bind deployment metadata; inventory may bind host/filesystem identity. These are
caller-owned transactions and do not establish authentication, quota enforcement,
readiness or permission to start a container. H03/H04 own population/behavior and
H02.3/H02.5 own host authority and actual device/mount/quota verification.

See the [shared initialization contract](../README.md) and
[H02.2 validation matrix](../../../docs/hosting/qualification/reports/HOSTED_MVP_H02_2_HANDOFF.md).
