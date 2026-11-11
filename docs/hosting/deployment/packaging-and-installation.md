# Hosted candidate packaging and installation

[Tool source](../../../application/deploy/hosted-mvp) · [Foundation guides](../foundation/README.md)

Build separate Admin and Operator OCI candidates and an offline host-agent bundle.
These are **unqualified infrastructure candidates**: they cannot start the hosted
application, enable accounts or provision services. Admin recovery, hosted access and
Operator recovery resources remain unavailable until H03–H05 deliver them. The
compiled Operator SPA is packaged but not served by the candidate launcher. The
[protected launch composition](protected-launch.md) validates protected bindings and keeps
normal hosted startup unavailable; later qualification owns promotion.

Use the [H02 design](../design/HOSTED_MVP_H02_DESIGN.md) for scope,
and the [measured handoff](../qualification/reports/HOSTED_MVP_H02_4_HANDOFF.md)
for exact observed artifacts, tool versions and limitations. No step below uses the
live demo, retained Lima quota-test VM, customer data or platform credentials.

## Prerequisites and local Docker

The prepared checkout needs its Python environment, `uv`, Node/npm and installed npm
workspace dependencies. `build-constraints.txt` pins the wheel builder. Use a fresh
private directory outside the checkout for each resolution/build. Do not use a moving
image tag or resolve Linux dependencies on macOS.

Docker Desktop is installed at `/Applications/Docker.app` on this Mac. Start that app
if necessary, then use its bundled CLI and credential helper:

```sh
export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"
docker version
```

The official app was copied from its verified Docker Desktop installer; Homebrew's
system-link postflight required sudo, so no system CLI links were installed. The
[official Mac installation instructions](https://docs.docker.com/desktop/setup/install/mac-install/)
cover app installation. Keep Docker Desktop and the retained Lima VM separate. The
observed Desktop engine is ARM64; the commands below explicitly build/run AMD64 under
emulation. This is not native Ubuntu or GCP qualification.

## Resolve target dependencies once

From `application/`, replace the example artifact path with a fresh private location.
All subsequent snippets use these variables in the same shell:

```sh
export EPM_ARTIFACTS="$HOME/Desktop/Property-Management-Data/hosted-mvp-qualification/H02.4-new"
export EPM_APPLICATION="$PWD"
export EPM_BASE='docker.io/library/python@sha256:1faf2343e747208b2a36e5f2b5ff908ec3b2d0078a6a7bfe73b535698fe83909'
mkdir -m 700 "$EPM_ARTIFACTS"
docker pull --platform linux/amd64 "$EPM_BASE"
docker run --rm --platform linux/amd64 --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=128m --workdir /tmp \
  --mount "type=bind,src=$EPM_APPLICATION/pyproject.toml,dst=/project.toml,readonly" \
  --mount "type=bind,src=$EPM_APPLICATION/deploy/hosted-mvp/resolve_lock.py,dst=/resolve.py,readonly" \
  --mount "type=bind,src=$EPM_ARTIFACTS,dst=/out" \
  "$EPM_BASE" python -B /resolve.py --project /project.toml \
  --output /out/linux-amd64 --architecture amd64
```

Only resolution needs public PyPI access. It records the actual Linux/Python platform,
project requirements/hash and every binary dependency's name/version/filename/hash.
Retain `resolution.json`, `dependencies.lock` and `wheels/` together. Reuse that closed
set for repeat builds; a fresh resolution may select newer permitted versions and is
a new candidate. Runtime S3 extras are not included in this default dependency set.

## Prepare and build the candidates

Preparation copies allowlisted Python runtime files, selected schemas and public
assets into fresh contexts. Tests, quota qualification harnesses, workspaces, arbitrary
data, source maps and environment files do not enter them. Only Operator preparation
runs `npm run build` and includes its compiled SPA; Admin UI remains unavailable.

```sh
for component in admin operator host_agent; do
  PYTHONPATH="apps/server:." .venv/bin/python scripts/hosted_package.py \
    --component "$component" --architecture amd64 \
    --lock "$EPM_ARTIFACTS/linux-amd64/dependencies.lock" \
    --wheelhouse "$EPM_ARTIFACTS/linux-amd64/wheels" \
    --output "$EPM_ARTIFACTS/$component"
done
for component in admin operator; do
  docker buildx build --platform linux/amd64 --network=none --load \
    --output "type=oci,dest=$EPM_ARTIFACTS/$component.oci.tar" \
    --metadata-file "$EPM_ARTIFACTS/$component-build.json" \
    --iidfile "$EPM_ARTIFACTS/$component-image-id" --provenance=false \
    --tag "epm-h02-$component:candidate" "$EPM_ARTIFACTS/$component"
done
.venv/bin/python deploy/hosted-mvp/archive_agent.py \
  "$EPM_ARTIFACTS/host_agent" "$EPM_ARTIFACTS/host-agent.tar.gz"
```

The wheel build is offline and needs setuptools 84.0.0 already in `uv`'s cache; obtain
that exact build dependency before an offline build if absent. Preparation invokes the
constraint by its filename from its own directory so checkout paths containing spaces
work. SOURCE_DATE_EPOCH is fixed. Docker installation verifies the app wheel, closed
hash lock and dependency wheel bytes before installing without network. The final
images copy only the installed environment from the builder, run as UID/GID 65532,
and contain no compiler or build-input directory. Schema staging is explicit and does
not create a database.

Retain the per-component `resources/hosted-candidate.json`: it records all app/resource
file hashes, exact implemented schema revisions, unavailable resource sets, architecture,
wheel and dependency-lock hashes. The agent archive has normalized sorted entries,
permissions, ownership and timestamps. It rejects unexpected files and never overwrites
an existing archive; retain a failed partial output for inspection before explicitly
choosing a new destination.

`containerimage.digest` in build metadata identifies the OCI platform manifest. Verify
it against `index.json` and the addressed blob in the OCI archive; the config digest is
a different identity. With this buildx exporter `--iidfile` contains the manifest digest,
not the config digest. Convenience tags do not qualify a release or replace digest pins.

## Installed checks outside the checkout

Use only temporary synthetic stores. The probe verifies exact installed inventories,
implemented schema initialization/validation, read-only matching Admin/inventory reinit,
no database creation for unavailable resources, compiler absence and blocked normal
startup. Admin/Operator liveness is 200; readiness, root and business routes are 503.

```sh
for component in admin operator; do
  docker run --rm --platform linux/amd64 --network none --read-only \
    --tmpfs /tmp:rw,noexec,nosuid,nodev,size=128m --workdir /tmp \
    --mount "type=bind,src=$EPM_APPLICATION/deploy/hosted-mvp/probe.py,dst=/probe.py,readonly" \
    --entrypoint /opt/epm/venv/bin/python "epm-h02-$component:candidate" \
    -B /probe.py --component "$component" > "$EPM_ARTIFACTS/$component-probe.json"
done
docker run --rm --platform linux/amd64 --network none --read-only \
  --tmpfs /tmp:rw,exec,nosuid,nodev,size=512m --workdir /tmp \
  --mount "type=bind,src=$EPM_ARTIFACTS/host-agent.tar.gz,dst=/agent.tar.gz,readonly" \
  --mount "type=bind,src=$EPM_APPLICATION/deploy/hosted-mvp/probe.py,dst=/probe.py,readonly" \
  --entrypoint /bin/sh "$EPM_BASE" -c \
  'mkdir /tmp/bundle && tar -xzf /agent.tar.gz -C /tmp/bundle && python -B /tmp/bundle/install_agent.py /tmp/agent && /tmp/agent/bin/python -B /probe.py --component host_agent'
```

The agent's temporary installation needs executable storage to create/run its Python
environment. This does not relax the separate Operator writable-tree sandbox, which
belongs to H02.5. The installer requires Python 3.14 and a fresh private destination;
it does not install systemd units, start the privileged agent, mount storage or bind a
host. Pin the target Python/platform again during native qualification. No checkout is
mounted inside these runtimes: only the standalone verification script/artifact.

Default local wheel commands remain unchanged: omit `--component` from
`stage_schema_resources.py` and `verify_installation.py`. Do not use candidate-specific
manifests as local workspace admission or as qualified release records.

## Focused validation

```sh
.venv/bin/python -m pytest \
  apps/server/app/platform/tests/test_hosted_artifacts.py \
  scripts/tests/test_hosted_packaging.py \
  apps/server/app/platform/tests/test_schema_resources.py \
  apps/server/app/platform/tests/test_hosted_schema.py -q
```

Run from `application/` so the `scripts` namespace is importable. These component and
Desktop packaging proofs alone establish no isolation/network/reboot/capacity/native/cloud
acceptance. Subsequent scoped H02 evidence is consolidated in the
[H02.11 handoff](../qualification/reports/HOSTED_MVP_H02_11_HANDOFF.md);
H03–H05 complete hosted behavior and final artifact promotion remain unavailable. They grant no invitation,
account access, automatic restart or live deployment authority.

For current reproducible development and native/reboot procedures, use the
[development and native qualification runbook](linux-development-and-qualification.md). It preserves the stopped baselines and separates
Desktop/emulated AMD64 from native ARM64 and future target-host acceptance.
