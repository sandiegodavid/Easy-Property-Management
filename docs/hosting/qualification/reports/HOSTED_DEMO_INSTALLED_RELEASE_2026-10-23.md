# Installed scratch release qualification — October 23, 2026

Dated qualification evidence. Results apply to the recorded fixture and release. For the
current deployment and remaining work, use the [qualification
register](../HOSTED_DEMO_PUBLIC_ACCESS_PLAN.md).

This follows the [actual R2 recovery/new-image drill](HOSTED_DEMO_RECOVERY_2026-10-23.md).
It qualifies the installed combined artifact and exact service configuration on scratch, not
an A/B deployment or public Cloudflare acceptance.

## Artifact and installation

The combined wheel was built from source commit `c8aab47415b42dba0dec3545b117143a95ce49ef`.
Frontend lint, formatting, type checking (184 source files), reproducible OpenAPI/contracts
and Vite compilation passed. Packaging used the existing build cache. Vite reported its
existing large-chunk warning; the build and content checks passed without a bundling-policy
change.

- Wheel: `easy_property_management-0.1.0-py3-none-any.whl`, `2982482` bytes.
- Wheel SHA-256: `6adcfb4fea6d953c5a83697417c2a0c2a081e66d1cf4288ad781d8327297fa85`.
- Transfer bundle SHA-256: `2f8e909ee9b1196b5f15820c111594781e5be4784eb89750e919f3247344de7e`.
- Root-owned isolated release: `/opt/epm/releases/qual-c8aab474`.

Wheel CRC/content checks passed, including byte matches for both recorded hosted
middleware/body files and absence of test files/source maps. A dedicated virtual environment
was created without modifying `demo-001`. Dependency versions were constrained to the
existing qualified runtime plus the separate S3 dependency set; the exact constraints are
retained in the new release. Matching Alembic resources were staged with
`stage_schema_resources.py`. The installed verifier confirmed the new site-packages path,
packaged web assets and schema revision `0001_initial_schema`, without a source-path
override.

The installed code environment is readable/executable by `epm-scratch`; workspace data and
credentials retain private ownership/modes. Readiness probes use the actual route contracts:
protected HTML requires identity, inactive units may unload, and fingerprinted public assets
have immutable caching.

## Real service and HTTP checks

The [installed-release report](../../evidence/HOSTED_DEMO_RELEASE_2026-10-23.json) records
use of the repository's `epm-hosted@.service`, changing only its explicit `HOSTED_RELEASE`
placeholder to `qual-c8aab474`. The materialized scratch instance was placed in
`/run/systemd/system`, not enabled. It used:

- `User=epm-scratch`, its real local workspace/configuration and quota image;
- protected `/etc/epm/hosted-scratch.json`;
- actual root-owned `0600` `/etc/epm/hosted-scratch.env`, with `EPM_PORT=18003`;
- the template's `TMPDIR`, private devices/temp, strict filesystem, no privileges,
  write-path restrictions and CPU/memory limits.

No `PYTHONPATH`/`PYTHONHOME` import override or R2/AWS credential variables were in the
service environment. Final startup became ready in **17.661 seconds**, with zero automatic
restarts. Sampled peak memory was `204075008` bytes; this is an idle startup observation,
not an operator-load or latency benchmark.

| Probe | Observed result |
| --- | --- |
| HTML `/sign-in` | 200, `Cache-Control: no-store` |
| Fingerprinted packaged JavaScript | 200, bytes equal to the wheel, `public, max-age=31536000, immutable` |
| Protected HTML `/` without identity | 303 to sign-in |
| `/api/hosted/session` without identity | 401, `no-store` |
| Session route with wrong host | 403 |

The unit then stopped cleanly with `ExecMainStatus=0`, zero restarts; its scratch volume was
unmounted and the exact loop device detached. A/B PIDs and activation times remained
unchanged through this installed-service drill. No Cloudflare key, TLS, email PIN, real
browser or public network was involved.

## Persistent-mount proposal and approval

The [boot proposal](../../evidence/HOSTED_DEMO_BOOT_PROPOSAL_2026-10-23.json) adds only:

```fstab
/var/lib/epm-volumes/epm-scratch.ext4 /var/lib/epm-scratch/volume ext4 loop,rw,nodev,nosuid,noexec,nofail,X-fstrim.notrim 0 0
```

`findmnt --verify` reported zero errors and one expected warning for a regular-file loop
source. The host's actual fstrim unit uses `--listed-in /etc/fstab:/proc/self/mountinfo`,
which is the documented mode for honoring `X-fstrim.notrim`; no TRIM was run against the
image. `nofail` permits host boot to continue after a mount failure; the application still
requires the exact valid bounded mount and fails closed.

The operator explicitly approved installing this entry and rebooting the VM, including the
temporary interruption of A/B. The installer checked the unchanged original/candidate fstab
hashes, retained the prior file root-only, atomically installed the candidate, and
successfully mounted by fstab. The owning account passed full workspace and installed
storage validation, then the scratch mount was removed before reboot so a subsequent mount
must come from boot.

## Approved reboot result

The [post-boot report](../../evidence/HOSTED_DEMO_BOOT_2026-10-23.json) confirms a changed
kernel boot ID and automatic mounting of the exact pinned scratch image. It still measures
`262144000` bytes and `512008` allocated blocks, with `rw,nosuid,nodev,noexec` mount flags.
Full workspace and installed storage checks passed as `epm-scratch` after boot. The original
scratch volume remains mounted; the separate recovery image remains detached. No scratch
application unit was enabled, and the temporary `/run` unit disappeared at reboot as
expected.

A/B returned active with new PIDs `572`/`573`. Their configuration, service-unit and
live-command hashes and business workspace IDs match the pre-boot checkpoint. Both returned
**200** for a bounded property read. This was an approved service interruption; neither
release nor workspace configuration was switched. Local recovery status after reboot still
reported no attention/retention pending.

These results qualify the scratch boot mount and installed startup, not persistent hosted
A/B units, A/B quota provisioning, real identity/PIN/TLS, public routes, four-session
workload, outage/reset/rollback coverage or a lost-host recovery. The qualification register
tracks subsequent evidence and remaining release gates.
