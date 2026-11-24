"""Explicit reviewed cloud arguments; no default project, shell strings or old-host adoption."""

import argparse
import ipaddress
import json
from pathlib import Path
import re
from typing import Literal

from pydantic import model_validator
from app.platform.hosted_contracts.values import CanonicalId, Contract


IPV4 = 4
SUBNET_PREFIX = 24


class Target(Contract):
    project: str
    region: str
    zone: str
    instance: str
    network: str
    subnet: str
    subnet_cidr: str
    repository: str
    service_account: str
    image: str
    image_project: Literal["ubuntu-os-cloud"] = "ubuntu-os-cloud"
    machine: Literal["e2-standard-2"] = "e2-standard-2"
    tunnel_id: CanonicalId

    @model_validator(mode="after")
    def safe(self):
        for value in (
            self.project,
            self.region,
            self.zone,
            self.instance,
            self.network,
            self.subnet,
            self.repository,
            self.service_account,
            self.image,
        ):
            if not re.fullmatch(r"[a-z][a-z0-9-]{0,61}[a-z0-9]", value):
                raise ValueError("Canonical cloud resource names are required")
        if not self.zone.startswith(self.region + "-"):
            raise ValueError("Zone and region must match")
        network = ipaddress.ip_network(self.subnet_cidr)
        if (
            network.version != IPV4
            or not any(
                network.subnet_of(ipaddress.ip_network(cidr))
                for cidr in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
            )
            or network.prefixlen != SUBNET_PREFIX
        ):
            raise ValueError("An explicit private /24 host subnet is required")
        if network.overlaps(ipaddress.ip_network("10.246.0.0/16")):
            raise ValueError("Host and Operator bridge ranges overlap")
        return self


def plan(target, startup):
    p, zone = "--project=" + target.project, "--zone=" + target.zone
    sa = target.service_account + "@" + target.project + ".iam.gserviceaccount.com"
    return [
        [
            "services",
            "enable",
            "compute.googleapis.com",
            "artifactregistry.googleapis.com",
            "secretmanager.googleapis.com",
            "logging.googleapis.com",
            "monitoring.googleapis.com",
            p,
        ],
        ["compute", "networks", "create", target.network, "--subnet-mode=custom", p],
        [
            "compute",
            "networks",
            "subnets",
            "create",
            target.subnet,
            "--network=" + target.network,
            "--region=" + target.region,
            "--range=" + target.subnet_cidr,
            p,
        ],
        [
            "compute",
            "firewall-rules",
            "create",
            target.network + "-iap",
            "--network=" + target.network,
            "--direction=INGRESS",
            "--action=ALLOW",
            "--rules=tcp:22",
            "--source-ranges=35.235.240.0/20",
            "--target-tags=epm-h02-host",
            p,
        ],
        ["iam", "service-accounts", "create", target.service_account, p],
        [
            "artifacts",
            "repositories",
            "create",
            target.repository,
            "--repository-format=docker",
            "--location=" + target.region,
            p,
        ],
        [
            "compute",
            "disks",
            "create",
            target.instance + "-data",
            "--size=50GB",
            "--type=pd-balanced",
            zone,
            p,
        ],
        [
            "compute",
            "instances",
            "create",
            target.instance,
            "--machine-type=" + target.machine,
            "--image=" + target.image,
            "--image-project=" + target.image_project,
            "--boot-disk-size=20GB",
            "--boot-disk-type=pd-balanced",
            "--service-account=" + sa,
            "--scopes=cloud-platform",
            "--network=" + target.network,
            "--subnet=" + target.subnet,
            "--tags=epm-h02-host",
            "--metadata=enable-oslogin=TRUE,block-project-ssh-keys=TRUE",
            "--metadata-from-file=startup-script=" + str(startup),
            "--disk=name="
            + target.instance
            + "-data,device-name=epm-h02-data,mode=rw,boot=no,auto-delete=no",
            "--no-restart-on-failure",
            "--shielded-secure-boot",
            zone,
            p,
        ],
    ]


def kms_plan(
    target: Target,
    *,
    keyring: str = "epm-h05-recovery",
    operator_key: str = "operator-workspace-kek",
    control_key: str = "admin-control-kek",
    next_rotation_time: str = "2027-02-21T00:00:00Z",
) -> list[list[str]]:
    """Explicit reviewed Cloud KMS provisioning commands for H05 off-host recovery."""
    for name in (keyring, operator_key, control_key):
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,61}[a-z0-9]", name):
            raise ValueError("Canonical Cloud KMS resource names are required")
    p = "--project=" + target.project
    loc = "--location=" + target.region
    sa = target.service_account + "@" + target.project + ".iam.gserviceaccount.com"
    return [
        ["services", "enable", "cloudkms.googleapis.com", p],
        ["kms", "keyrings", "create", keyring, loc, p],
        [
            "kms",
            "keys",
            "create",
            operator_key,
            loc,
            "--keyring=" + keyring,
            "--purpose=encryption",
            "--protection-level=software",
            "--rotation-period=90d",
            "--next-rotation-time=" + next_rotation_time,
            p,
        ],
        [
            "kms",
            "keys",
            "create",
            control_key,
            loc,
            "--keyring=" + keyring,
            "--purpose=encryption",
            "--protection-level=software",
            "--rotation-period=90d",
            "--next-rotation-time=" + next_rotation_time,
            p,
        ],
        [
            "kms",
            "keys",
            "add-iam-policy-binding",
            operator_key,
            loc,
            "--keyring=" + keyring,
            "--member=serviceAccount:" + sa,
            "--role=roles/cloudkms.cryptoKeyEncrypterDecrypter",
            p,
        ],
        [
            "kms",
            "keys",
            "add-iam-policy-binding",
            control_key,
            loc,
            "--keyring=" + keyring,
            "--member=serviceAccount:" + sa,
            "--role=roles/cloudkms.cryptoKeyEncrypterDecrypter",
            p,
        ],
    ]


MAX_BUDGET_USD = 1000
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
_DOMAIN_RE = re.compile(
    r"^(?=.{4,253}$)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
    r"(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$"
)
_BILLING_RE = re.compile(r"^[A-F0-9]{6}-[A-F0-9]{6}-[A-F0-9]{6}$")
_PROJECT_NUM_RE = re.compile(r"^[0-9]{6,20}$")


def ops_agent_config() -> str:
    """Return hardened GCP Ops Agent YAML for epm-h02-host (30d Cloud Logging + host metrics).

    Secret redaction is enforced strictly at the application logger (`hosted_logging.py`).
    Docker JSON logs and systemd journald streams use separate pipelines with matching parsers.
    """
    return """logging:
  receivers:
    epm_systemd:
      type: systemd_journald
    epm_docker_json:
      type: files
      include_paths:
        - /var/lib/docker/containers/*/*-json.log
  processors:
    parse_docker_json:
      type: parse_json
      time_key: time
      time_format: "%Y-%m-%dT%H:%M:%S.%L%z"
  service:
    pipelines:
      epm_systemd_logs:
        receivers: [epm_systemd]
      epm_docker_logs:
        receivers: [epm_docker_json]
        processors: [parse_docker_json]
metrics:
  receivers:
    hostmetrics:
      type: hostmetrics
      collection_interval: 60s
  service:
    pipelines:
      epm_host_metrics:
        receivers: [hostmetrics]
"""


def _alert_policy(
    display_name: str,
    condition_name: str,
    metric_filter: str,
    *,
    threshold_value: float,
    options: tuple[str, str, str] = ("0s", "COMPARISON_GT", "ALIGN_MEAN"),
) -> dict[str, object]:
    duration, comparison, aligner = options
    return {
        "displayName": display_name,
        "combiner": "OR",
        "conditions": [
            {
                "displayName": condition_name,
                "conditionThreshold": {
                    "filter": metric_filter,
                    "comparison": comparison,
                    "thresholdValue": threshold_value,
                    "duration": duration,
                    "aggregations": [
                        {
                            "alignmentPeriod": "60s",
                            "perSeriesAligner": aligner,
                        }
                    ],
                },
            }
        ],
    }


def observability_plan(
    target: Target,
    *,
    notification_email: str,
    heartbeat_host: str = "epmdemo.xyz",
    billing: tuple[str, str] | None = None,
    monthly_budget_usd: int = 250,
) -> dict[str, object]:
    """Explicit reviewed GCP Monitoring, Logging, Ops Agent & Budget plan (H06.7 / D3 / D9)."""
    if not _EMAIL_RE.fullmatch(notification_email):
        raise ValueError("A valid operational owner notification_email is required.")
    if not _DOMAIN_RE.fullmatch(heartbeat_host):
        raise ValueError("A canonical heartbeat_host domain is required.")
    if not (1 <= monthly_budget_usd <= MAX_BUDGET_USD):
        raise ValueError("monthly_budget_usd must be between 1 and 1000.")
    billing_account: str | None = None
    project_number: str | None = None
    if billing is not None:
        billing_account, project_number = billing
        if not _BILLING_RE.fullmatch(billing_account):
            raise ValueError("Canonical GCP billing account ID (XXXXXX-XXXXXX-XXXXXX) is required.")
        if not _PROJECT_NUM_RE.fullmatch(project_number):
            raise ValueError(
                "Numeric GCP project_number is required for --filter-projects in Billing Budgets."
            )

    p = "--project=" + target.project
    sa = target.service_account + "@" + target.project + ".iam.gserviceaccount.com"
    commands: list[list[str]] = [
        [
            "services",
            "enable",
            "logging.googleapis.com",
            "monitoring.googleapis.com",
            "billingbudgets.googleapis.com",
            p,
        ],
        [
            "projects",
            "add-iam-policy-binding",
            target.project,
            "--member=serviceAccount:" + sa,
            "--role=roles/logging.logWriter",
        ],
        [
            "projects",
            "add-iam-policy-binding",
            target.project,
            "--member=serviceAccount:" + sa,
            "--role=roles/monitoring.metricWriter",
        ],
        [
            "logging",
            "buckets",
            "update",
            "_Default",
            "--location=global",
            "--retention-days=30",
            p,
        ],
        [
            "beta",
            "monitoring",
            "channels",
            "create",
            "--display-name=EPM Pilot 0 Owner Email",
            "--type=email",
            "--channel-labels=email_address=" + notification_email,
            p,
        ],
        [
            "logging",
            "metrics",
            "create",
            "epm_hosted_recovery_alerts",
            "--description=Hosted recovery overdue/failure alerts (H05/H06)",
            '--log-filter=(jsonPayload.event="hosted_recovery_alert" OR '
            'textPayload:"hosted_recovery_alert") AND severity>=WARNING '
            'AND NOT textPayload:"\\"backup_recovered\\""',
            p,
        ],
        [
            "logging",
            "metrics",
            "create",
            "epm_host_guardian_containment",
            "--description=Host guardian container containment events (H02/H06)",
            '--log-filter=jsonPayload.event="runtime_containment_attention" OR '
            'textPayload:"runtime_containment_attention"',
            p,
        ],
        [
            "logging",
            "metrics",
            "create",
            "epm_host_inode_headroom",
            "--description=Host inode utilization > 80% alerts (H06.7)",
            '--log-filter=jsonPayload.event="host_inode_headroom_alert" OR '
            'textPayload:"host_inode_headroom_alert"',
            p,
        ],
        [
            "monitoring",
            "uptime",
            "create",
            "epm-pilot0-host-heartbeat",
            "--resource-type=uptime-url",
            "--resource-labels=host=" + heartbeat_host + ",project_id=" + target.project,
            "--protocol=https",
            "--path=/",
            "--period=5",
            "--timeout=10",
            p,
        ],
    ]
    if billing_account is not None and project_number is not None:
        commands.append(
            [
                "billing",
                "budgets",
                "create",
                "--billing-account=" + billing_account,
                "--display-name=EPM Pilot 0 Monthly Gross Spend ($" + str(monthly_budget_usd) + ")",
                "--budget-amount=" + str(monthly_budget_usd) + "USD",
                "--filter-projects=projects/" + project_number,
                "--credit-types-treatment=exclude-all-credits",
                "--threshold-rule=percent=0.5",
                "--threshold-rule=percent=0.8",
                "--threshold-rule=percent=1.0",
            ]
        )

    policies = {
        "backup_alerts": _alert_policy(
            "EPM Backup Overdue or Failure Alert",
            "epm_hosted_recovery_alerts > 0",
            (
                'metric.type="logging.googleapis.com/user/epm_hosted_recovery_alerts" '
                'AND resource.type="gce_instance"'
            ),
            threshold_value=0.0,
            options=("0s", "COMPARISON_GT", "ALIGN_SUM"),
        ),
        "containment_alerts": _alert_policy(
            "EPM Host Guardian Containment Alert",
            "epm_host_guardian_containment > 0",
            (
                'metric.type="logging.googleapis.com/user/epm_host_guardian_containment" '
                'AND resource.type="gce_instance"'
            ),
            threshold_value=0.0,
            options=("0s", "COMPARISON_GT", "ALIGN_SUM"),
        ),
        "disk_headroom": _alert_policy(
            "EPM Host Disk Utilization > 80%",
            "Disk percent_used > 80%",
            (
                'metric.type="agent.googleapis.com/disk/percent_used" '
                'AND resource.type="gce_instance" '
                'AND metric.labels.state="used"'
            ),
            threshold_value=80.0,
            options=("300s", "COMPARISON_GT", "ALIGN_MEAN"),
        ),
        "inode_headroom": _alert_policy(
            "EPM Host Inode Utilization > 80%",
            "epm_host_inode_headroom > 0",
            (
                'metric.type="logging.googleapis.com/user/epm_host_inode_headroom" '
                'AND resource.type="gce_instance"'
            ),
            threshold_value=0.0,
            options=("0s", "COMPARISON_GT", "ALIGN_SUM"),
        ),
        "memory_headroom": _alert_policy(
            "EPM Host Memory Utilization > 85%",
            "Memory percent_used > 85%",
            (
                'metric.type="agent.googleapis.com/memory/percent_used" '
                'AND resource.type="gce_instance" '
                'AND metric.labels.state="used"'
            ),
            threshold_value=85.0,
            options=("300s", "COMPARISON_GT", "ALIGN_MEAN"),
        ),
        "cpu_headroom": _alert_policy(
            "EPM Host CPU Utilization > 85%",
            "CPU utilization > 85% for 10m",
            ('metric.type="agent.googleapis.com/cpu/utilization" AND resource.type="gce_instance"'),
            threshold_value=0.85,
            options=("600s", "COMPARISON_GT", "ALIGN_MEAN"),
        ),
        "host_loss_heartbeat": _alert_policy(
            "EPM Host Loss External Heartbeat Failure",
            "External HTTPS uptime check failed",
            (
                'metric.type="monitoring.googleapis.com/uptime_check/check_passed" '
                'AND resource.type="uptime_url" '
                'AND metric.labels.check_id="epm-pilot0-host-heartbeat"'
            ),
            threshold_value=1.0,
            options=("300s", "COMPARISON_LT", "ALIGN_FRACTION_TRUE"),
        ),
    }

    return {
        "commands": commands,
        "alert_policies": policies,
        "ops_agent_config_yaml": ops_agent_config(),
        "log_retention_days": 30,
        "monthly_budget_usd": monthly_budget_usd,
        "budget_excludes_credits": True,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--startup", type=Path, required=True)
    args = parser.parse_args()
    target = Target.model_validate_json(args.target.read_text())
    print(json.dumps(plan(target, args.startup.resolve(strict=True)), indent=2))
