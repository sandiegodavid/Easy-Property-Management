# Scratch systemd and physical upload evidence — October 23, 2026

Dated qualification evidence. Results apply to the recorded fixture and release. For the
current deployment and remaining work, use the [qualification
register](../HOSTED_DEMO_PUBLIC_ACCESS_PLAN.md).

Result: the hosted CLI started under the planned systemd sandbox, and real 50 MiB
multipart/concurrent-admission and original-result checks passed. The product owner
explicitly approved scratch-only systemd/upload qualification. A/B remained on their
unchanged private release.

This extends the [Linux SQLite FULL evidence](HOSTED_DEMO_LINUX_QUOTA_2026-10-23.md). It
does not qualify Cloudflare, the final combined wheel, reboot, generic File
endpoint-specific behavior, or off-host recovery.

## Provenance and systemd startup

The VM, scratch account/image/workspace, existing Python 3.14.9 runtime and isolated test
dependencies are the same as the preceding evidence. The root-owned source snapshot is based
on `39fcc45ce04b3882a57d3380e1508c9cb158b36a`. A/B's installed environment was not changed.
No new packages were installed in this run.

Temporary units were installed under `/run/systemd/system/`, not enabled for boot:

- `epm-quota-startup.service`: actual `python -m app ... serve-hosted`, with explicit
  scratch configuration/deployment and port `18003`.
- `epm-quota-upload.service`: a scratch-only launcher composing the same application,
  substituting **only** remote signing-key discovery with a local synthetic RSA
  public key. Real RS256 verification, pending enrollment, explicit synthetic-subject
  activation, opaque sessions, CSRF, storage/mount validation, owning APIs and SQLite
  remained enabled. No extra test-control endpoints were added.

Both used the production template's service identity, private working/TMPDIR paths, one
writer, mount requirement, `NoNewPrivileges`, empty capabilities, `PrivateTmp`,
`PrivateDevices`, `ProtectHome`, `ProtectSystem=strict`, `ProtectKernelTunables`,
`ProtectControlGroups`, restricted namespaces, writable volume/access paths only,
`MemoryHigh=1G`, `MemoryMax=1500M` and `CPUQuota=90%`. Qualification-specific differences
were explicit scratch paths/name, the source `PYTHONPATH`/existing interpreter instead of an
installed new wheel, inline environment instead of the deployment env file, and the upload
fixture's launcher/key-discovery substitution. `systemd-analyze verify` accepted both on
systemd `255.4-1ubuntu8.18`.

The actual CLI completed startup and listened only on `127.0.0.1:18003`. Readiness was
checked after the application startup-complete log. `Type=simple` service activation alone
is not application readiness. Verified responses:

| Request | Actual result |
| --- | --- |
| Exact scratch Host, missing identity proof, protected bootstrap | `401 hosted_assertion_rejected`, `no-store` |
| Direct loopback Host, protected bootstrap | `403 hosted_host_rejected`, `no-store` |

The CLI process was stopped before the upload fixture started. No second scratch writer ran
alongside it. Both units ultimately stopped with exit status zero and zero automatic
restarts. Observed current memory was about 198 MiB for the startup unit and 245 MiB for the
upload unit; these are snapshots, **not peak/RAM capacity or four-browser latency
qualification**. `MemoryPeak` was unavailable after stop.

## Request-body and storage-error contract

Admission reserves three simultaneous body copies. The body spool closes after its final
replay chunk, before owning-handler publication, while the reservation continues through
operation/response completion. Storage errors use bounded `ENOSPC`/`EDQUOT` cause traversal
(at most eight causes) and return a typed quota result even if cleanup has restored free
space. Unrelated permission errors are not classified as quota errors. A response already
started is terminated rather than replaced by a second HTTP response.

These contracts retain the original operation key for explicit outcome recovery. The
retained [earlier measurements](../../evidence/HOSTED_DEMO_UPLOAD_BEFORE_2026-10-23.json)
include a 40960-byte sampled low-water point; the passing run below is the acceptance
evidence for the final handling. Before/after artifacts and source snapshots remain
available for provenance.

The VM test used an updated, stopped **scratch source snapshot**. Its original files were
preserved as `request_body.before.py` and `middleware.before.py`. Final VM checksums matched
the local working tree:

| File | SHA-256 |
| --- | --- |
| `hosted_access/api/request_body.py` | `0f39aa5e7412195086265e8e2a7c9a42b3b95f715eccaa49a86e4d0fc0a62c66` |
| `hosted_access/api/middleware.py` | `1f06ddff88c3363997ca86ed797d998a800b4b0ef191871ff2def0f890463590` |

## Successful physical upload and recovery checks

The repeat used real loopback HTTP and real multipart body bytes through `POST
/api/intake/sources/import`, including the owning File publication path. It was not an
in-process TestClient or mocked disk test. The synthetic client explicitly supplied the
secure-cookie value on the private loopback hop, emulating an HTTPS terminator; this does
**not** prove browser cookie transport, Cloudflare PIN/JWT discovery, or TLS ingress
behavior.

1. Send headers and 2 MiB of the first 50 MiB file, then hold its body open. Verify
   at least 1 MiB is actually spooled on the bounded volume using statvfs.
2. Send a second 50 MiB request's headers while the first reservation is held.
   It returns typed `507 hosted_storage_quota_exceeded` **before its body is sent**.
3. Finish the first body. It returns `200`, one source, one attachment and one
   original command receipt. The sampled minimum available space is `37646336`
   bytes (about 35.9 MiB), above the 16 MiB write-headroom threshold.
4. An immediate receipt read initially receives conservative `507` while the
   first request's final reservation is still unwinding. A later **explicit read
   of the same original key** returns the original source/operation. The 50 MiB
   mutation is not resubmitted. The rejected command has no receipt (`404`) at
   this point.
5. Download and hash all `52428800` file bytes through the protected File API.
   SHA-256 matches the submitted bytes:
   `8729453030852d9b0f3833ade105a67a3285dc69e3947ca4597fe5906fddc568`.
6. Submit a 1 MiB body using the previously unadmitted second key. It returns `200`,
   demonstrating that reservations were released and the earlier rejection did
   not leave a false owning receipt. Payload alteration here is allowed because
   the original request was rejected before owning dispatch; this is not a retry
   of an acknowledged/unknown mutation with a changed fingerprint.
7. Stop the scratch writer and run complete retained-workspace validation. It
   succeeds for the same scratch workspace UUID.

The [successful original JSON
report](../../evidence/HOSTED_DEMO_UPLOAD_AFTER_2026-10-23.json) records `passed: true`, the
initial transient receipt status, subsequent original result, byte hash and small retry.
Completion time was October 23, 2026, 21:02 PDT (`2026-10-24T04:02:15Z`). Sampling is an
observation, not a proof that no shorter unsampled disk low point can occur in every
workflow.

Report SHA-256 values:

- Before: `b40a7875126cf640bec4012dd4f2ea83310d49e7891122393ac57a4a25b21392`.
- After: `020574292452f9e0ebf24099f326a2186c3eaca49dacba4a38ff20a58ef93d5d`.

## Regression checks, cleanup and remaining gates

Focused local validation: **225 passed, one Linux-only skip** across hosted access, Intake,
local browser transport and web delivery. New regressions cover disk-spool
lifetime/byte-exact replay, raw and wrapped quota errors after cleanup, unrelated errors,
cyclic exception causes, safe HTTP translation and late-response handling. Ruff lint/format
checks pass on all four changed Python files; `git diff --check` passes. Frontend
source/assets were unchanged, so frontend checks were not rerun for this backend-only delta.

After both scratch processes stopped, the exact loop backing image/mount mapping was
rechecked, the scratch filesystem unmounted and its loop device detached. Port 18003 had no
listener afterward. The image still measured exactly 250 MiB, root-owned `0600`, with
`512008` allocated blocks. No image, account, evidence, uploaded file or workspace was
deleted. Temporary inactive units remain in `/run` until reboot; they are not enabled.
Source/helpers, synthetic private key/session state and reports remain in private scratch
directories for follow-up. Those synthetic keys are accepted only by the stopped fixture,
never A/B or production.

A/B main PIDs remained `8726`/`8727`, active since `2026-10-23T17:50:37Z`, before and after.
Host disk remained about 17% used with about 24 GiB free. No A/B data, release, unit
configuration, firewall, DNS, tunnel or R2 settings changed.

Follow-on [R2 recovery/remount](HOSTED_DEMO_RECOVERY_2026-10-23.md) and [installed
release/boot](HOSTED_DEMO_INSTALLED_RELEASE_2026-10-23.md) evidence are recorded separately.
This report establishes the stated sandbox/startup and one real Intake/File upload/receipt
path. Other endpoint/fault and real-client gates are tracked in the qualification register.
