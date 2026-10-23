# Scratch R2 recovery and new-volume qualification — October 23, 2026

The administrator authorized a synthetic scratch backup/publication/restore drill.
No A/B service switch, host reboot, public route or invitation was performed.
The drill completed at October 23, 22:01 PDT; machine reports use October 24 UTC.
This supplements the [systemd/upload qualification](../../qualification/reports/HOSTED_DEMO_SYSTEMD_UPLOAD_2026-10-23.md).

## Credentials and execution boundary

The operator created `epm-private-recovery` and entered the saved S3 endpoint and
bucket-scoped credentials through an interactive hidden-input wizard on the VM.
`/etc/epm/recovery-scratch.json` passed the real configuration loader and is
root-owned `0600`; `/var/lib/epm-recovery/scratch` and its staging directory are
root-owned `0700`. Credentials were not displayed, copied into this repository,
passed as command arguments, or supplied to A/B. Successful authenticated object
operations validate the entered S3 credentials, not the bucket's public-access
dashboard settings; public access must remain disabled.

The existing source qualification tree under `/opt/epm/qualification/quota-39fcc45c`
was used, including the previously recorded spool/error fixes. This is **not an
installed final-wheel qualification**. The existing release environment was not
modified. Optional dependencies were installed separately into its `s3-deps`
directory: boto3/botocore `1.43.118`, s3transfer `0.19.3`, jmespath `1.1.0`,
python-dateutil `2.9.0.post0`, urllib3 `2.8.0`, six `1.17.0`.

Synthetic backup and reference passphrases were generated privately on the VM and
retained root-only under `/var/lib/epm-recovery/scratch/drill-20261023`. These are
test artifacts, not a production passphrase-custody or host-loss procedure.

## Verified off-host round-trip

The [recovery report](../../evidence/HOSTED_DEMO_RECOVERY_2026-10-23.json) records:

- Production `create_hosted_backup()` completed as `epm-scratch`, using the real
  fixed-volume checks, stopped-writer lock, production encryption, full archive
  validators and external account-private staging. Workspace UUID remains
  `1eb0d18b-f130-45a0-a043-1cd3d27979cf`.
- `publish_archive()` revalidated the administrator-private archive copy, uploaded
  through the actual R2 adapter, read back the complete object and durably saved
  the verification ledger. `retentionPending` and `needsAttention` were false at
  publication. No remote objects were deleted; the scratch ledger began empty.
- A separate full GET produced the restore input. Its size and SHA-256 matched
  the local encrypted archive: `120115` bytes,
  `6b96dc774128fc1ccfabefe465c6592a5d567d83a6976bf8ea7559d3c697d5ce`.
- The actual restore service restored into a new destination, and complete
  retained-data validation passed. All **42 original rows across 105 tables**
  remained unchanged, preserving original IDs, relationships and audit history;
  restore adds its own audit record. Both original files, **53,477,376 bytes
  (51 MiB)** total, matched their original hashes. The highly repetitive synthetic
  content compresses well: this did not transfer a 51 MiB encrypted object.
- The separate encrypted administrator reference bundle was uploaded, fully read
  back, independently downloaded and decrypted. Its synthetic approved subject
  reference survived; the allowlisted format requires fresh enrollment and omits
  usable session/lease/credential state. Its `references/` object is manually
  retained, outside the business-archive retention ledger.

The first reference export was invoked as root and correctly rejected by the
administrative database's ownership guard. Export then passed as `epm-scratch`;
only the encrypted result was handled by the root R2 publisher. No guard was
relaxed and the completed business backup was not repeated.

The fixture contains Intake/File records and synthetic receipts/history. It does
not contain populated Finance or Maintenance workflows: this does not independently
qualify financial totals or every feature's backup/restore coverage. First-point
success does not qualify multi-day pruning, retention repair, failed remote writes
or failed read-back; existing source tests cover those cases separately.

## Fresh bounded restore and remount

The [new-image report](../../evidence/HOSTED_DEMO_REMOUNT_2026-10-23.json) qualifies the
corrected provisioning recipe on a **new** root-owned `0600` image:
`/var/lib/epm-volumes/epm-scratch-recovery.ext4`. The prior scratch image was not
formatted or resized. Creation used `fallocate` for exactly `262144000` bytes,
then `mkfs.ext4 -m 10 -E nodiscard,lazy_itable_init=0,lazy_journal_init=0`.

Allocation remained `512008` 512-byte blocks after formatting, first mount,
restoration, unmount/device detach and second mount. No corrective reallocation
was needed. Both mounts used `rw,nodev,nosuid,noexec`. The owning service account
restored the downloaded archive into the new volume and passed complete retained
validation and the real storage-budget checks on both mounts. Available ordinary
space was `141598720` bytes, with **30 MiB root-only recovery blocks**.

A separate fresh administrative database was initialized outside the new volume.
It has no approved subject, pending enrollment, session or draft lease, and its
operator is inactive. The source administrative database was not copied. This
proves fresh authority starts empty; it does not prove a real Cloudflare enrollment
or restoration of a lost production host.

## Retained artifacts, cleanup and remaining gates

At the end of this recovery drill both scratch images were unmounted and their
loop devices detached. Images,
archives, restored workspaces, private passphrase files, helpers and reports are
retained for follow-up; immutable evidence was not manually deleted. The new
restored workspace is under
`/var/lib/epm-scratch/recovery-drill-20261023/volume/workspace` inside the detached
new image. Its protected qualification configuration is
`/opt/epm/qualification/quota-39fcc45c/deployment-recovery.json`.

A/B remained active with the same PIDs (`8726`/`8727`) and activation timestamp
(`2026-10-23T17:50:37Z`). Final host disk use was 19%, with about 23 GiB free.
Neither A/B runtime, configuration, firewall, DNS, tunnel nor invitations changed.
R2 now contains the two encrypted synthetic objects recorded in the report.

Subsequent [installed-release and approved reboot qualification](../../qualification/reports/HOSTED_DEMO_INSTALLED_RELEASE_2026-10-23.md)
passed: the original scratch volume is now persistently mounted; its hosted
application is stopped. A/B restarted on their unchanged private release as part
of the approved reboot. Remaining Slice 7 gates include A/B deployment bindings
and physical failure/reset/rollback checks. Slice 8 still requires actual Cloudflare identity,
public-route, browser/cache and remote-network latency qualification. The operator
confirmed they do not yet own a domain. No stable public link is configured.
