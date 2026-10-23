# Linux quota qualification evidence — October 23, 2026

Result: the real unprivileged SQLite FULL/rollback drill passed twice on a third,
disposable workspace on the existing VM. This closes that specific physical quota
test gate, **not all of Slice 7**. No A/B service, workspace, installed package,
DNS, tunnel, invitation or R2 configuration was changed.

The product owner explicitly authorized IAP SSH, verifying the existing release,
provisioning this scratch account/250 MiB volume, and running/saving the drill.
The loop filesystem was unmounted and its loop device detached afterward; no
persistent mount or new systemd service was installed.

## Tested environment and provenance

| Item | Observed value |
| --- | --- |
| VM | `epm-demo`, `project-47b72bb7-ba90-42c9-910`, `us-west1-b` |
| Kernel / architecture | Linux `7.0.0-1014-gcp`, x86_64 |
| Application source | `39fcc45ce04b3882a57d3380e1508c9cb158b36a` |
| Source snapshot SHA-256 | `04a018598df68059a3825adf0a5ca19157e06ba6e425a71a6fed2c0e79205895` |
| Source snapshot contents | Tracked `application/apps/server`, `application/database`, `alembic.ini`, `pyproject.toml`, plus the one-off scratch initialization helper |
| Source location on VM | `/opt/epm/qualification/quota-39fcc45c`, root-owned/read-only to scratch user |
| Python | Existing `/opt/epm/releases/demo-001/venv/bin/python`, CPython `3.14.9` |
| Application import | Current source via explicit `PYTHONPATH`, **not** `demo-001`'s old application modules |
| Runtime dependencies inspected | SQLAlchemy `2.1.6`, Pydantic `2.14.1`, cryptography `46.0.7` |
| SQLite | `3.53.1` |
| Isolated test dependencies | pytest `8.4.2`, iniconfig `2.3.1`, packaging `26.3`, pluggy `1.7.0`, pygments `2.21.0` |
| Test dependency location | `/opt/epm/qualification/quota-39fcc45c/test-deps`; existing release environment unchanged |
| Disposable identity | `epm-scratch`, system account, non-login shell |
| Disposable workspace UUID | `1eb0d18b-f130-45a0-a043-1cd3d27979cf` |
| Workspace / staging | `/var/lib/epm-scratch/volume/workspace`, `/var/lib/epm-scratch/volume/tmp`, service-owned `0700` |
| Backing image | `/var/lib/epm-volumes/epm-scratch.ext4`, root-owned `0600` |
| Image logical size | Exactly `262144000` bytes (250 MiB) |
| Final image allocation | `512008` 512-byte blocks, at least the logical size |
| Mounted device during test | `/dev/loop4`; verified pinned backing image before use and detach |
| Mount | Complete ext4 filesystem, `rw,nosuid,nodev,noexec,relatime` |
| Config | Root-owned `0640`, `/opt/epm/qualification/quota-39fcc45c/deployment.json`; `.invalid` synthetic identity, no provider credentials |
| Final evidence time | October 23, 2026, 20:51 PDT; `2026-10-24T03:51:49Z` |

The initial VM release was verified as `demo-001`, Python 3.14.9. It predates the
hosted storage implementation and was not upgraded or represented as qualified.
The test deliberately uses current source with existing runtime dependencies.
This does not substitute for qualifying the final combined wheel/systemd release.

## Initial failure and provisioning correction

The first run correctly failed **before** the FULL drill: the backing image had
fallen from full allocation to `480024` 512-byte blocks after first mount/workspace
initialization, while its logical length remained 250 MiB. The production adapter
rejected this; its check was not mocked, skipped or relaxed.

The provisioning used `mkfs.ext4 -m 10 -E nodiscard`, but left lazy inode/journal
initialization at its defaults. Deferred initialization is a plausible explanation
for the observed first-mount deallocation: mke2fs documents background inode-table
initialization, and the Linux loop driver can implement zeroing as hole punching.
No block trace was captured, so the exact request causing the holes is not proven.
See [mke2fs initialization options](https://man7.org/linux/man-pages/man8/mke2fs.8.html)
and [Linux loop request handling](https://github.com/torvalds/linux/blob/master/drivers/block/loop.c).

After checking the exact scratch image length, root used
`fallocate --keep-size --length 262144000` on **only that image** to re-reserve
holes after initialization. This did not resize, reformat or replace its data.
Allocation became `512008` blocks and remained there across both successful runs.
The [operations runbook](../../operations/HOSTED_DEMO_OPERATIONS.md) now requires disabling deferred
initialization for new images, verifying allocation again after first mount and
workspace initialization, and excluding these reserved images from discard/TRIM.
The revised clean-format recipe still needs an independent fresh-image/reboot
qualification; the passing test here used the explicitly recorded reallocation.

## Test execution and result

The actual test was
`test_real_sqlite_full_rolls_back_and_kernel_retains_recovery_headroom` in
`application/apps/server/app/modules/hosted_access/tests/test_linux_storage_qualification.py`.
It ran as `epm-scratch`, not root, with:

```text
TMPDIR=/var/lib/epm-scratch/volume/tmp
PYTHONDONTWRITEBYTECODE=1
PYTHONPATH=/opt/epm/qualification/quota-39fcc45c/application/apps/server:/opt/epm/qualification/quota-39fcc45c/test-deps
EPM_TEST_HOSTED_QUOTA_DEPLOYMENT=/opt/epm/qualification/quota-39fcc45c/deployment.json
EPM_TEST_HOSTED_QUOTA_LOCAL_CONFIG=/var/lib/epm-scratch/config.json
```

Pytest cache was disabled. The scratch-only destructive marker was present. The
test created a separate temporary SQLite database on the bounded volume and:

1. Opened it in WAL mode with `synchronous=FULL`.
2. Committed an acknowledged row.
3. Inserted 1 MiB BLOBs in a new immediate transaction until real `SQLITE_FULL`.
4. Rolled back and verified **only** the acknowledged row remained.
5. Verified `PRAGMA integrity_check` was `ok`, the image stayed exactly 250 MiB,
   and at least 16 MiB of root-only blocks remained.
6. Checked upload admission against actual remaining capacity when the test's
   post-rollback condition applied; this is **not** a concurrent HTTP upload test.

The corrected runs reported `1 passed in 7.37s` and `1 passed in 6.38s`, with no
skips. The latter's [original JUnit report](../../evidence/HOSTED_DEMO_QUOTA_2026-10-23.xml)
records one test, zero failures/errors/skips. Its SHA-256 is
`36c5e80e2b130bb1ed2062b12c4d6a9de2a2fd9b31695324219f6689b73e718c`.

Final statvfs evidence used 4096-byte blocks: `55317` free blocks and `47637`
available to an unprivileged user, a root-only difference of `31457280` bytes
(30 MiB), exceeding the 16 MiB requirement. Free inode count was `63980`.
These are post-cleanup facts, not a measurement taken at the instant of FULL.

## Isolation, retained artifacts and remaining gates

A/B were active before and after the drill with unchanged main PIDs `8726` and
`8727` and unchanged activation time `2026-10-23T17:50:37Z`. Host disk remained
about 17% used, with about 24 GiB available. No host-full drill was attempted.

Only the new scratch filesystem was unmounted and `/dev/loop4` detached after
checking both the mount source and backing image. The account (non-login), 250 MiB
image, source/test-dependency directory and reports remain recoverable for follow-up;
no workspace/image/account was deleted. The administrator home also retains the
uploaded `source.tar`, `provision_scratch.sh` and exported `epm-quota-39fcc45c.xml`.
Do not rerun provisioning over those existing targets. Reinspect the actual loop
mapping on any later mount; `/dev/loop4` is not a persistent device identity.

Still pending before Slice 7 is complete:

- Clean-format allocation stability and persistent remount/reboot qualification.
- Final installed wheel/environment qualification. Subsequent template-equivalent
  [systemd startup and one real 50 MiB concurrent-upload/recovery path](../../qualification/reports/HOSTED_DEMO_SYSTEMD_UPLOAD_2026-10-23.md)
  passed after a targeted staging fix; other physical fault/endpoint paths remain pending.
- Actual private R2 publication/read-back, encrypted reference-bundle recovery,
  downloaded archive restore, and daily-operation evidence.
- Auth-key/tunnel outage, failed reset, host-disk maintenance and release/data rollback drills.

No Cloudflare/domain/R2 credentials or A/B switch were authorized by this scratch
procedure. Slice 8 and operator invitations remain blocked.
