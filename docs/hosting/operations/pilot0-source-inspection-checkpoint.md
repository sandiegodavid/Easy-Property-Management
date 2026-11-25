# Pilot 0 Admin source inspection checkpoint

Updated 2026-11-25. The source inspector is live on GCP and the requested Operator release is registered.

The Admin runtime now requests a read through the UID-authenticated identity relay. The relay resolves the registered Operator. Admin checks the workspace and access epoch before dispatch, and the Operator checks its current binding before returning effective access and logical storage usage. A missing reading continues to surface as unavailable.

Focused validation passed with 32 tests across the handoff, identity relay, and Admin HTTP suites. The Unix socket test verifies usage, effective access, binding, and rejection of a mismatched epoch. Ruff lint and format checks passed.

The Admin catalog has qualified release `00000000-0000-4000-8000-000020261125` for `epm-pilot0-operator:pilot0-20261125-tasks` at digest `sha256:7ffcc9c01986883c7b741f5a1a7ba4d75335313ecf08a5309e31cf0baaad2a18`. Its qualification reference records the operator-approved exception for this rollout. The immutable manifest and pre-insert catalog backup are in `/var/backups/epm-release-catalog` on the host.

The live inspector rollout uses Operator digest `sha256:0df8161dd3c57901920a550ff60b57f4d86a2a96a843a3569e4172de1c7d9808`, Admin digest `sha256:55ea7220e69d03c16223d5c646551682f55f855b6cced83342b48e6b0e64e19c`, and the staged relay interpreter at `/opt/epm/host-agent-source-inspector-20261125`. Both Operator readiness endpoints returned 200. A read from the live Admin container through the actual relay returned enabled access and usage of 8,687,771 of 50,000,000 bytes for Demo A and 2,347,008 of 50,000,000 bytes for WWJDF. The browser's **Refresh source** action remains to be verified with an Admin session. The five-check suite was skipped by request for this rollout. The [previous failures](../../ui/demo-a-smoke-results-2026-11-25.md) remain open.

Rollback assets include the original relay interpreter, the launcher backup `/opt/epm/h0312/run_identity.py.before-source-inspector-20261125`, and the stopped Operator containers suffixed `-before-source-inspector`. The shared identity override is `95-source-inspector.conf`.

## Admission image selection and Demo C

The VM launcher now resolves the qualified image assigned to the Operator in Admin, checks its local digest, and passes the immutable Docker image ID to the container. The [admission runbook](pilot0-admission-and-incidents.md#2-standard-manual-pilot-0-admission-flow) uses the same image for workspace provisioning, recovery initialization, and the first backup. The launcher keeps the baseline's catalog digest and local Docker image ID mapping explicit. It stops if an existing container runs a different image, so an assignment revision sync cannot silently perform a rollout. Launcher rollback file: `/opt/epm/pilot0/launch_operator.py.before-assigned-image-20261125`.

The staged launcher resolved both the latest qualified release and the baseline against the live catalog before installation. Fresh scratch databases passed schema validation in the tasks and source inspector images. Both newer images rejected constraints on an isolated copy of Demo C's old workspace, so the initial in-place rollout was rolled back.

On 2026-11-25, with operator approval, Demo C moved to `pilot0-20261125-tasks` on a fresh empty workspace under the same operator and workspace IDs. Docker reported healthy, `/health/ready` returned 200, and Admin recorded the release as applied and reflected the new verified recovery point. The old local workspace and temporary rollback copies were removed. The five-check live smoke suite was skipped by request.
