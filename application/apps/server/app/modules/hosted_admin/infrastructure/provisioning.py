"""Pinned provisioning steps with a verified manual ingress gate, never browser assertions.

The composition supplies protected host discovery/maintenance and fixed Linux
effects. All resource identities are derived here from an acknowledged draft.
"""

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
import json
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field

from app.modules.hosted_admin.application.contracts import AdminError
from app.modules.hosted_admin.application.operations import (
    Observation,
    OperationIntent,
    Reservation,
    fingerprint,
)
from app.modules.hosted_admin.application.setup import SetupData
from app.modules.hosted_admin.infrastructure.cloudflare_setup import CloudflareSetup


class ProvisioningConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    deployment_kind: str = Field(pattern=r"^synthetic_demo$")
    hostname_suffix: str = Field(pattern=r"^[a-z0-9]+(?:[.-][a-z0-9]+)+$")
    release: str = Field(pattern=r"^release-[0-9]{8}-[0-9]{2,}$")
    release_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    profile: str = Field(pattern=r"^[a-z0-9-]{1,80}$")
    template_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    memory_bytes: int = Field(gt=0)
    disk_bytes: int = Field(ge=250 * 1024 * 1024)
    port_start: int = Field(ge=1024, le=64535)
    issuer: str = Field(pattern=r"^https://[a-z0-9-]+\.cloudflareaccess\.com$")
    account: str = Field(pattern=r"^[a-f0-9]{32}$")
    # A protected signed verifier report records actual remaining account seats
    # and qualification for this exact release/template/profile, with expiry.
    readiness_report: str = Field(pattern=r"^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$")


@dataclass(frozen=True)
class ProvisioningDependencies:
    store: object
    source: object
    discovery: object
    qualification: object
    reports: object
    platform: object


class ProvisioningHost:
    def __init__(self, dependencies):
        self.d = dependencies

    def config(self):
        return ProvisioningConfig.model_validate(self.d.platform.configuration())

    def options(self):
        try:
            config = self.config()
            return {
                "releases": [config.release],
                "templates": ["synthetic", "empty"],
                "workspace_mib": 250,
                "file_mib": 50,
                "backup_policy": "Private encrypted off-host recovery verification required before access is enabled.",
            }
        except OSError, ValueError:
            return {
                "releases": [],
                "templates": [],
                "workspace_mib": 250,
                "file_mib": 50,
                "backup_policy": "Provisioning configuration needs private installation.",
            }

    def plan(self, draft_id, data):
        config = self.config()
        if data.release != config.release:
            raise AdminError("admin_release_unqualified", 409)

        def identifier(label):
            return str(uuid5(NAMESPACE_URL, f"epm-setup:{draft_id}:{label}"))

        key = "d-" + identifier("instance").replace("-", "")[:16]
        # A deterministic port is retried only through a NEW reviewed setup if
        # occupied. It is never silently switched after allocation admission.
        port = config.port_start + int(identifier("port").replace("-", "")[:8], 16) % 1000
        paths = self.d.platform.paths_for(key)
        values = {
            "hostname": key + "." + config.hostname_suffix,
            "port": str(port),
            "user": "epm-" + key,
            "workspace": identifier("workspace"),
            "email": data.email,
            "mount": str(paths["volume"]),
            "image": str(paths["image"]),
            "disk": key,
            "memory": key,
        }
        reservations = [
            Reservation(
                kind=kind,
                identity=value,
                amount=config.disk_bytes
                if kind == "disk"
                else config.memory_bytes
                if kind == "memory"
                else 0,
            ).model_dump()
            for kind, value in sorted(values.items())
        ]
        return {
            "key": key,
            "instance_id": identifier("instance"),
            "allocation_id": identifier("allocation"),
            "operator_id": identifier("operator"),
            "workspace_id": identifier("workspace"),
            "hostname": values["hostname"],
            "port": port,
            "profile": config.profile,
            "config_hash": fingerprint(config.model_dump()),
            "reservations": reservations,
        }

    @contextmanager
    def admission(self, draft_id, data):
        with self.d.platform.lock():
            plan = self.plan(draft_id, data)
            config = self.config()
            report = self.d.reports.report(config.readiness_report)
            registered = self.d.source.inventory.list()
            discovered = self.d.discovery.keys()
            self.d.platform.preflight(plan, config)
            snapshot = self.d.qualification.snapshot()
            yield {
                "plan": plan,
                "config": config,
                "report": report,
                "registered": registered,
                "discovered": discovered,
                "snapshot": snapshot,
            }

    def check(self, connection, plan, prepared):
        config, report = prepared["config"], prepared["report"]
        if plan["config_hash"] != fingerprint(config.model_dump()):
            raise AdminError("admin_setup_configuration_changed", 409)
        expected = {
            "release": config.release,
            "profile": config.profile,
            "template_digest": config.template_digest,
            "release_digest": config.release_digest,
            "configuration_hash": fingerprint(config.model_dump()),
        }
        if (
            any(report.get(key) != value for key, value in expected.items())
            or report.get("qualified") is not True
            or not 0 <= self.d.store.clock() - report.get("observed", 0) < 300
            or report.get("expires", 0) <= self.d.store.clock()
        ):
            raise AdminError("admin_setup_readiness_unverified", 409)
        pending = connection.execute(
            "SELECT count(*) FROM operation o WHERE o.kind='provision' AND NOT EXISTS (SELECT 1 FROM reservation r WHERE r.operation_id=o.id AND r.kind='hostname' AND r.identity IN (SELECT value FROM json_each(?)))",
            (json.dumps(prepared["snapshot"].retained_hostnames),),
        ).fetchone()[0]
        if type(report.get("remaining_seats")) is not int or report["remaining_seats"] <= pending:
            raise AdminError("admin_provider_seats_unavailable", 409)
        registered = prepared["registered"]
        retained_emails = {item.email.casefold() for item in registered}
        retained_emails.update(
            row[0].casefold()
            for row in connection.execute("SELECT identity FROM reservation WHERE kind='email'")
        )
        email = next(item["identity"] for item in plan["reservations"] if item["kind"] == "email")
        if email.casefold() in retained_emails:
            raise AdminError("admin_operator_email_exists", 409)
        if set(prepared["discovered"]) - {item.key for item in registered}:
            raise AdminError("admin_inventory_reconciliation_required", 409)
        intent = OperationIntent(
            operation_id="00000000-0000-4000-8000-000000000000",
            kind="provision",
            target=plan["key"],
            expected_revision=0,
            reason="Fresh synthetic demo",
        )
        self.d.qualification.admission_check(
            connection,
            intent,
            [Reservation.model_validate(item) for item in plan["reservations"]],
            snapshot=prepared["snapshot"],
        )

    def desired(self, payload):
        setup = payload["setup"]
        data = SetupData.model_validate(setup["data"])
        expected = self.plan(setup["draft_id"], data)
        if expected != setup["plan"] or payload["target"] != expected["key"]:
            raise AdminError("admin_setup_configuration_changed", 409)
        return data, expected, self.config()

    def inspect(self, payload, step):
        data, plan, config = self.desired(payload)
        with self.d.platform.lock():
            if step in {"allocate", "workspace"}:
                return self.d.platform.inspect(payload, step, config)
            provider = self.provider(config).verify(plan["hostname"], data.email)
            if provider is None:
                return Observation("waiting")
            if step == "provider_setup":
                self.d.platform.verify_ingress(plan)
                return Observation("verified", {"verified": True}, provider["application"])
            if step == "readiness":
                deployment = self.deployment(data, plan, config, provider["audience"])
                observed = self.d.platform.readiness(payload, deployment)
                if observed.state == "verified":
                    report_id = str(
                        uuid5(NAMESPACE_URL, payload["operation_id"] + ":pre-enrollment")
                    )
                    try:
                        report = self.d.reports.report(report_id)
                    except FileNotFoundError:
                        return Observation("waiting")
                    expected = {
                        "operation_id": payload["operation_id"],
                        "workspace_id": plan["workspace_id"],
                        "configuration_digest": self.d.platform.deployment_digest(plan),
                        "encrypted_archive": True,
                        "independent_readback": True,
                        "workspace_validated": True,
                    }
                    if (
                        set(report) != set(expected) | {"observed", "expires"}
                        or any(report.get(key) != value for key, value in expected.items())
                        or not 0 <= self.d.store.clock() - report["observed"] < 86400
                        or report["expires"] <= self.d.store.clock()
                    ):
                        raise AdminError("admin_pre_enrollment_recovery_unverified", 409)
                return observed
        raise AdminError("admin_setup_step_invalid", 409)

    def apply(self, payload, step):
        data, plan, config = self.desired(payload)
        with self.d.platform.lock():
            # The platform reconciles exact ownership for partial steps and
            # refuses all unowned populated destinations. Nothing is deleted.
            if step == "readiness":
                provider = self.provider(config).verify(plan["hostname"], data.email)
                if provider is None:
                    raise AdminError("admin_provider_enforcement_unverified", 409)
                self.d.platform.verify_ingress(plan)
                self.d.platform.start(
                    payload, self.deployment(data, plan, config, provider["audience"])
                )
            else:
                self.d.platform.apply(payload, step, config)

    def provider(self, config):
        return CloudflareSetup(config.account, self.d.platform.provider_token(), config.issuer)

    @staticmethod
    def deployment(data, plan, config, audience):
        capabilities = ["records.read", "files.read"]
        if data.access == "read_write":
            capabilities += ["records.write", "files.write"]
        return {
            "deployment_mode": "hosted_demo",
            "public_origin": "https://" + plan["hostname"],
            "identity_issuer": config.issuer,
            "identity_audience": audience,
            "workspace_id": plan["workspace_id"],
            "operator_id": plan["operator_id"],
            "allowed_email": data.email,
            "administrator_contact": data.support,
            "enabled_at": datetime.fromtimestamp(data.starts, UTC).isoformat(),
            "expires_at": datetime.fromtimestamp(data.expires, UTC).isoformat(),
            "capabilities": capabilities,
        }

    def contain(self, payload):
        # Target-only service stop plus source-owned disable when an access store
        # exists. Allocated bytes/configuration are retained for private review.
        with self.d.platform.lock():
            return self.d.platform.contain(payload)

    def enrollment(self, instance):
        deployment, status = self.d.source.access_snapshot(instance)
        self.d.discovery.source_command_ready(self.d.source.inventory.get(instance))
        if not status["binding_matches_configuration"]:
            raise AdminError("admin_source_binding_changed", 409)
        return {
            "approved": status.get("identity_approved", False),
            "status": status,
            "issuer": deployment["identity_issuer"],
            "email": deployment["allowed_email"],
            "starts": datetime.fromisoformat(
                deployment["enabled_at"].replace("Z", "+00:00")
            ).timestamp(),
            "expires": datetime.fromisoformat(
                deployment["expires_at"].replace("Z", "+00:00")
            ).timestamp(),
        }

    def check_grant(self, instance):
        snapshot = self.d.qualification.snapshot()
        self.d.qualification._fresh(snapshot)
        with self.d.store.transaction() as connection:
            capacity = connection.execute("SELECT * FROM capacity WHERE id=1").fetchone()
            if (
                not capacity
                or capacity["environment_hash"] != snapshot.environment_hash
                or snapshot.active_count > capacity["ceiling"]
            ):
                raise AdminError("admin_capacity_unqualified", 409)
        if snapshot.memory_committed * 4 > snapshot.memory_total * 3:
            raise AdminError("admin_physical_capacity_blocked", 409)
        self.d.source.prepare(instance)
