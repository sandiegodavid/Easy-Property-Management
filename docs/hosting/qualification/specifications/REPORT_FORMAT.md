# Common qualification report v1

The executable field contract is
[models.py](../../../../application/apps/server/app/platform/hosted_proofs/models.py).
This is evidence JSON, not a database schema or a second release-qualification store.
All records forbid extra fields and coercion; bounds prevent unbounded documents.

A report identifies a run UUID, proof/owner, exact JSON specification SHA/revision,
source commit and dirty flag, recorded/start/finish UTC epoch milliseconds, actual
execution level/environment, exact input-manifest digest and driver reference,
source/tool/image/schema/workload/configuration pins, evidence artifact references/
digests, one result per planned case, overall result and remaining limits.

Required pins must all be explicit even for an unrun report. A pin is `pinned` with
its SHA-256 or `unavailable`/`not_applicable` with a reason and no invented digest.
Source pins hash the exact checked-out source manifest (including dirty files), not
only the commit string. Schema pins hash all selected versioned resources; tool pins
include actual versions and binary/source digests. Image pins mean actual artifact/
OCI/VM image bytes for the stated level; a component fixture must be labelled as
such and cannot stand in for a deployed image. Sanitized configuration/workload
manifests contain no secrets. Run inputs pin the paired procedure Markdown as well
as case JSON; retain each exact revision for reproduction.

`source_commit`/`source_dirty` may be null only while nothing executed. Executed
cases need source identity, input-manifest reference/hash, actual ordered execution
times and retained observations. Scope uses `component`, `native_linux`,
`docker_linux`, `gcp`, `deployed_browser` or `manual`. Linux scopes require actual
Linux kernel/filesystem facts; Docker/GCP require actual container runtime identity;
cloud/deployed-browser scopes require protected provider configuration identity.
Record unavailable environment fields as null with a case reason/remaining limit;
never describe a Mac contract test as native Linux evidence.

Case outcomes are:

- `passed`: actual observation plus retained evidence references/digests, no missing
  case or required input pin. This is still only a claim pending owning review.
- `failed`: actual unexpected result and retained failure evidence; do not erase it.
- `not_run`: planned but unexecuted, with an explanation, no fabricated measurements.
- `unavailable`: a concrete prerequisite/driver/provider/tool is unavailable, with
  reason; no fabricated measurement or successful native result.

Overall precedence is failed, then unavailable, then not-run, then passed. Thus a
mixed partial scan cannot look passed. Cases cannot be omitted/duplicated; references
must resolve to the report's evidence inventory. A pass requires every declared input
pin to be available/pinned. No unrun report can invent start/finish times. At least
one explicit remaining-limit statement is required, including for a pass (for example
“Component scope only; native/cloud acceptance not established”). Measurements use
nonnegative signed-64-bit integers and explicit bytes/inodes/milliseconds/count/
USD-micros/minutes units; raw prose is bounded to 1,000 characters per observation.

The validator checks neither remote evidence bytes nor provider signatures; owners
verify those through scoped tooling and review. Plain strings are not a secret scanner:
report authors must sanitize evidence/observations. Never store raw argv containing
credentials. The invocation instead records a registered driver, immutable private
input manifest, phase and repetition. Paths/credentials remain in protected setup,
not arbitrary execution parameters. Reports do not authorize host effects or restores.

No sample “passed” report is committed by H01.5. Synthetic values live only in tests.
Older report formats are historical evidence; do not rewrite them into v1 or relabel
old passes. The [acceptance register](../HOSTED_MVP_ACCEPTANCE.md) links reviewed new
reports with their precise scope and keeps unresolved release gates open.
