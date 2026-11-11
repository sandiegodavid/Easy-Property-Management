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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--startup", type=Path, required=True)
    args = parser.parse_args()
    target = Target.model_validate_json(args.target.read_text())
    print(json.dumps(plan(target, args.startup.resolve(strict=True)), indent=2))
