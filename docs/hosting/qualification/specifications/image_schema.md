# Image/schema packaging proof — H02

Case authority: [image_schema.json](image_schema.json). Apply the
[common invocation/safety contract](README.md) and [packaging handoff](PACKAGING_HANDOFF.md).
Component and Linux-Docker results are separate; a component fixture cannot qualify
an installed release. H02 owns implementation after its detailed design.

## Setup and invocation

Use pinned source/tools and fresh synthetic destinations for six independent store
families across separate Admin/Operator/agent artifacts. Seed no user/account/session
implicitly. The private input manifest pins compatibility manifests, exact schema/
asset inventories, build settings and environment; image IDs are registered immutable
artifacts. No checkout/live workspace/credentials inside the tested artifact.

Inspect with the common `describe --spec .../image_schema.json` command. The exact
reserved execution interface is:

```bash
.venv/bin/python -m app.platform.hosted_proofs execute --spec ../docs/hosting/qualification/specifications/image_schema.json --inputs /private/proof/inputs.json --output /private/proof/report.json --phase run
```

H01 exits 3 without effects; H02 supplies actual safe build/install driver commands.

## Workload, negative controls and observations

| Case | Reproducible workload / required observation |
| --- | --- |
| `build_separate_artifacts` | Build from one pinned source/input set twice; record immutable Admin/Operator/agent digests, owned manifests and declared reproducibility limits. Reject using a tag alone or mismatched component assignment. |
| `inventory_resources` | Enumerate every selected INI/environment/baseline/revision/asset and hash; compare exact per-component resource inventory, including separate Admin recovery and no undeclared private store. |
| `fresh_initialize_all_stores` | For each owning store, fresh-init once, run exact revision/structure/constraint validator and record empty-data/disabled-access state. No resource set may report initialized while its baseline is absent. |
| `existing_store_read_only` | Repeat matching-store initialization; compare DB bytes/logical rows and grant/revision state. Wrong store/revision/structure is rejected without change. |
| `missing_wrong_resources` | In separate throwaway copies remove each required resource in turn and substitute wrong revisions/store baselines; prove missing-resource error before file creation, no alternate DDL/checkout fallback. |
| `wrong_component_manifest` | Supply Admin image for Operator, wrong API/agent/schema/assignment and unavailable qualification; admission rejects before container/effect dispatch. |
| `partial_initializer` | Inject interruption before/after schema write/commit and artifact publication boundaries; verify no empty baseline stamp/adoption, retained partial state and explicit cleanup. |
| `asset_secret_exclusion` | Inventory packaged paths and compare allowlist; negative copies include fake credential/env/source-map/DB/private-key markers and must fail. Never include real secrets to test exclusion. |
| `installed_without_checkout` | Launch the installed entry points from another CWD with checkout/PYTHONPATH absent and network fallback disabled; inspect local/hosted resources independently. Missing UI/baseline stays unavailable. |

## Evidence and cleanup

Record build commands/settings by immutable input manifest, tool/image/schema/asset
hashes, initialization structural inventories, DB comparison hashes and safe rejected
variant output. All cases require evidence; a missing real baseline remains unavailable.
Keep failed artifact copies and partial stores privately; destroy only proven disposable
resources by registered ID after evidence retention. No local installation script is
rewritten or current release acceptance claimed by this specification.
