# H02 packaging and installation proof handoff

H01.5 inspected the existing
[staging script](../../../../application/scripts/stage_schema_resources.py),
[installation verifier](../../../../application/scripts/verify_installation.py) and
[wheel builder](../../../../application/scripts/build_wheel.sh).
Staging currently copies only `alembic.ini` and `database/sqlite-migrations`; it
rejects symlinks and an existing target and attempts rollback if the second rename
fails. Installation verifies packaged web assets and the business revision discoverable
through `product_migrations`, not independent stores or complete structural validity.
The wheel's package-data list includes compiled public assets, not hosted schema sets.
These are reusable safety concepts, **not** fresh hosted packaging acceptance.
Scripts/local launch behavior and wheel metadata remain unchanged by H01.5.

## Declared artifacts and resources

| Component/tool | Required owning schema resources |
| --- | --- |
| Admin OCI image | Main Admin plus separate Admin recovery |
| Operator OCI image | Business, hosted access and per-operator recovery |
| Restricted host-agent artifact | Protected host inventory; no business/identity store access |
| Future Tenant/Owner public web bundles | No owned resources/DDL; exact API/source business-readable compatibility only |
| Local Operator | Existing business and declared local recovery boundary, without hosted login/Admin authority |

Pin each real baseline/environment/configuration/version file and compiled public
asset to an immutable component manifest. Use H01.4's exact artifact/API/agent/schema
compatibility contract; the agent's inventory revision is a peer pin, not an Admin
SQL mount. All five hosted resource sets are H01.2 unavailable scaffolds, so H02–H05
must deliver actual baselines and validators before a corresponding installed proof
can pass. Do not stamp empty stores or turn `heads=[]` into readiness.

## Required installation procedure and negative controls

1. Pin clean/dirty source and all build/runtime tools. Build separate Admin/Operator
   immutable artifacts, not one mutable image/tag for every portal. Inventory manifest
   digests, assets, required resources and bootstrap commands without secrets.
2. Export/install each artifact into a fresh isolated Linux environment. Remove checkout
   access, change working directory, omit ambient source/PYTHONPATH and network fallback.
   Resolve packaged resources from the installed root only. Keep a separate untouched
   test artifact for each negative variant; never mutate a registered release in place.
3. For each declared store, initialize a new private synthetic destination using its
   owning resources, validate exact revision **and** resource-derived structure, then
   repeat read-only and prove no data/grants/session/revision mutation. Recovery stores
   must initialize without opening damaged business/main Admin data.
4. Remove each required resource/config/baseline/asset in turn; substitute another
   store/component/revision; add an undeclared private schema, incompatible API/agent
   or mutable image reference. All must reject before service enablement/store write,
   without alternate DDL or downloading a missing resource from the checkout.
5. Fault initialization and both publication boundaries, including commit failure.
   Retain partial-file evidence; never auto-adopt/stamp/reset. Check injected failure
   rolls back owning work or yields explicit unavailable/needs-attention without
   claiming initialized. Do not insert accounts/sessions as a side effect.
6. Inspect artifact contents for source maps, environment files, credentials, live DBs,
   workspace content and private keys. Record counts and safe file/digest inventory.
   Test hosted/local composition separately; local behavior remains supported.

Actual build/launch/initialization commands belong to H02's reviewed detailed design
and per-owner implementations. Until then the common executor exits unavailable;
no current wheel/staging script is claimed to package the new stores. H02 records
installed component results against every [image/schema case](image_schema.json)
and attaches structural inventories, negative-control output and cleanup evidence.
