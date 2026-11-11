# Hosted deployment tools

Detailed documentation lives in [docs/hosting](../../../docs/hosting/README.md).
Start with the [foundation guides](../../../docs/hosting/foundation/README.md) for
architecture, behavior and qualification limits. Runbook commands keep the existing
`application/` working directory and tool paths.

| Tools | Runbook |
| --- | --- |
| Packaging scripts, Dockerfiles and offline agent installer | [Packaging and installation](../../../docs/hosting/deployment/packaging-and-installation.md) |
| `launch/`, fixed hosted entry points and status probes | [Protected launch](../../../docs/hosting/deployment/protected-launch.md) |
| `lab/`, Compose and immutable-source fixtures | [Development and native qualification](../../../docs/hosting/deployment/linux-development-and-qualification.md) |
| `gcp/`, startup, disk setup and host proofs | [GCP host setup](../../../docs/hosting/deployment/gcp-host-setup.md) |
| `sandbox/`, private runtime and guardian fixtures | [Runtime supervision](../../../docs/hosting/operations/runtime-supervision.md) |
| `gateway/`, ingress/egress and host-service fixtures | [Network and host services](../../../docs/hosting/operations/network-and-host-services.md) |

These are scoped infrastructure tools. Qualification evidence does not grant
operator admission, business ingress or release-promotion authority.
