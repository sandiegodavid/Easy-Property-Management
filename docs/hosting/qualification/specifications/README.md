# H01.5 proof specifications

Specifications and document validation are delivered. **No target proof executor or
new native/cloud/provider/end-user acceptance is delivered.**
[H01.5](../../design/HOSTED_MVP_H01_DESIGN.md#h015--specify-proof-inputs-reports-and-packaging-handoff)
assigns these proofs; the [acceptance register](../HOSTED_MVP_ACCEPTANCE.md) records
actual review outcomes. Do not replace historical reports or import their status.

| Proof / reproducible procedure | Accountable owner | Supporting owners | Report scopes (separate reports) |
| --- | --- | --- | --- |
| [Image/schema packaging](image_schema.md) / [case manifest](image_schema.json) | H02 | — | Component, Linux Docker |
| [Runtime and physical limits](runtime_limits.md) / [case manifest](runtime_limits.json) | H02 | H04 source/commitments | Native Linux, Linux Docker, exact GCP target |
| [Identity and handoff](identity_handoff.md) / [case manifest](identity_handoff.json) | H03 | — | Component, deployed browser |
| [Logical usage accounting](usage_accounting.md) / [case manifest](usage_accounting.json) | H04 | H02 physical enforcement | Component, Linux Docker, exact GCP target |
| [Workspace/control recovery](recovery.md) / [case manifest](recovery.json) | H05 | H02 runtime, H03 current identity | Component, Linux Docker, exact GCP target, deployed browser |
| [Supported operations and economics](operations_economics.md) / [case manifest](operations_economics.json) | H04 | H06 operational acceptance | Manual rehearsal, exact GCP target, deployed browser |

The case manifests enumerate required observations, not passed tests. The paired
procedures own setup, workload, negative controls, measurements and cleanup. Changing
either changes the required evidence: pin both files as inputs. Every case must appear
in a report even if not run or unavailable. Every declared scope needs its own proof
where the release gate requires it; a component report never substitutes for Linux,
Docker, GCP, managed provider or browser acceptance. Reviewers compare source/artifact/
configuration pins across reports and reject stale or incompatible evidence.

## Safe invocation and executor handoff

From `application/` (replace `image_schema` with any proof ID in the table):

```bash
.venv/bin/python -m app.platform.hosted_proofs describe --spec ../docs/hosting/qualification/specifications/image_schema.json
.venv/bin/python -m app.platform.hosted_proofs validate --spec ../docs/hosting/qualification/specifications/image_schema.json --report /private/proof/report.json
```

`describe` prints requirements, never performs a test. `validate` reads bounded JSON
(maximum 1 MiB per input), validates shape, exact specification SHA/revision/owner,
all cases, references, input pins, timestamps and scope. Exit 0 means a valid report
claiming a pass **within its declared scope**, not authenticated evidence or release
approval. Exit 2 means a valid failed/not-run/unavailable report; exit 1 means invalid
input/coverage/pins or unreadable input. Document-validation errors never echo document contents or paths.
There is no automatic acceptance-register edit, manifest qualification or source enable.

The exact future executor interface is reserved, but currently always exits **3**
with `proof_executor_unavailable`, before reading any supplied path or writing output:

```bash
.venv/bin/python -m app.platform.hosted_proofs execute --spec ../docs/hosting/qualification/specifications/image_schema.json --inputs /private/proof/inputs.json --output /private/proof/report.json --phase run
```

Phases are `run`, `after-reboot`, `manual`. No executor dispatch, dynamic plugin,
shell command, sudo, network call, cloud provisioning, reboot or default lab root is
implemented. H02/H03/H04/H05 must implement and review their allowlisted driver and
strict input-manifest model before enabling their proof. H01 never supplies a
customer restore/decrypt command. The retained Lima lab and live demo host are untouched.

A future private input manifest must pin: run UUID; exact proof/scope/phase; source
commit/dirty-tree manifest; exact component/VM images and compatibility manifests;
all owning schema resources and tool versions/binary hashes; sanitized provider,
identity, key-policy and filesystem profiles; disposable resource IDs; deterministic
fixture/workload digest and reference time; repetition/concurrency settings; abort/
capacity limits; private evidence destination and reviewed cleanup identities. These
are registered references resolved by that driver, not arbitrary shell or customer
paths. Actual provider credentials and encryption keys stay outside inputs/reports.
The owning detailed design must specify real setup commands and least-privilege
credentials; this interface does not imply that setup is already implemented.

## Common safety and retained-failure contract

- Use isolated synthetic operators, fake people/files and dedicated provider resources.
  No real customer workspace, production access store, live host or credential capture.
- Native destructive tests need an explicitly reviewed disposable Linux target,
  qualified filesystem, root lab opt-in and independent lab snapshot. Mac Docker
  Desktop results cannot qualify Linux project enforcement or the Google target.
- A missing driver, unavailable tool/provider/privilege, unknown capacity or failed
  prerequisite is recorded `unavailable`/`not_run`; never fill a hypothetical pass.
  Abort before mutation when target identity/ownership cannot be proven.
- Preserve negative controls and raw failure captures privately, sanitize references
  for reports and record safe artifact digests. No cookies, JWTs, credentials, raw
  provider responses, business content, or plaintext recovery material in git.
- Cleanup is explicit and ownership-verified. Stop before destructive cleanup of
  failed/unknown state; retain original operation/resource/evidence identities for
  inspection. Never prune an older good backup because a new run started.
- Release gates require owning review of actual artifacts and security evidence.
  JSON validation proves consistency only and does not authenticate pins or results.

See the [report format](REPORT_FORMAT.md), [packaging handoff](PACKAGING_HANDOFF.md)
and [quota reuse boundary](../HOSTED_PROJECT_QUOTA_REUSE.md). Historical imports stay
byte-for-byte unchanged; new environment/source pins require new reports.
