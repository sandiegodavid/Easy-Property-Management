# Hosting deployment

Run commands from `application/` unless a runbook states otherwise. Tool source lives in
`application/deploy/hosted-mvp/`.

**Release gate:** Pilot 0 releases at **H06** after H05 supplies verified off-host backup
protection and rehearsed restore. These runbooks maintain closed business ingress until
H05/H06 promotion.

## Runbooks

| Task | Runbook |
| --- | --- |
| Build separate OCI images and install the offline host agent | [Packaging and installation](packaging-and-installation.md) |
| Build and deploy H03/H04 shared Admin and Operator identity candidates | [Identity candidates](identity-candidates.md) |
| Validate protected launch bindings and unavailable status | [Protected hosted launch](protected-launch.md) |
| Run Docker Desktop, retained Linux/Lima labs, and reboot proofs | [Development and native qualification](linux-development-and-qualification.md) |
| Prepare the retained GCP filesystem/services and qualify `epm-h02-host` | [GCP host setup and qualification](gcp-host-setup.md) |
| Inspect private runtime, supervision, gateway, and identity operations | [Operations runbooks](../operations/README.md) |

## Related References

- [Foundation guides](../foundation/README.md): architectural boundaries and measured capacity.
- [Acceptance register](../qualification/HOSTED_MVP_ACCEPTANCE.md): release-proof gates.
- [H04/H05 handoff exit review](../qualification/reports/HOSTED_MVP_H04_10_EXIT_REVIEW_2026-11-22.md): latest GCP native qualification state.
