"""Target-only fenced configuration cutovers; immutable source receipts own retries."""

from dataclasses import asdict, replace
from datetime import UTC, datetime
import hashlib
import json
import pwd

from app.modules.hosted_access.application.admin_commands import AccessResult
from app.modules.hosted_access.application.configuration import HostedDeployment
from app.modules.hosted_admin.infrastructure.cloudflare_setup import CloudflareSetup
from app.modules.hosted_admin.application.contracts import AdminError
from app.modules.hosted_admin.application.operations import canonical


class AccessCutover:
    def __init__(self, source, platform):
        self.source, self.platform = source, platform

    def desired(self, payload):
        reference = payload["source_reference"]
        original = HostedDeployment.model_validate(reference["deployment"])
        values = original.model_dump(mode="json")
        if payload["action"] == "renew":
            values.update(
                enabled_at=datetime.fromtimestamp(payload["starts"], UTC).isoformat(),
                expires_at=datetime.fromtimestamp(payload["expires"], UTC).isoformat(),
            )
        else:
            values["allowed_email"] = payload["replacement_email"]
        return HostedDeployment.model_validate(values).model_dump(mode="json")

    def checked(self, payload):
        before = payload["source_reference"]["instance"]
        current = self.source.inventory.get(payload["instance"])
        if any(
            getattr(current, key) != before[key]
            for key in (
                "instance_id",
                "allocation_id",
                "operator_id",
                "workspace_id",
                "access_database",
                "user",
                "release",
                "local_config",
            )
        ):
            raise AdminError("admin_source_binding_changed", 409)
        desired = self.desired(payload)
        path = self.source.paths.configs / f"hosted-{current.key}.json"
        actual = self.platform.h.read_json(path, self.source.paths)
        if (
            actual != desired
            and hashlib.sha256(path.read_bytes()).hexdigest()
            != payload["source_reference"]["deployment_digest"]
        ):
            raise AdminError("admin_source_binding_changed", 409)
        return current, desired, path

    def lookup(self, payload):
        with self.platform.lock():
            current, desired, path = self.checked(payload)
            receipt = self.source._transport(
                asdict(current),
                {
                    "query": "receipt",
                    "command": self.source._command(payload).model_dump(),
                },
            )
            if not receipt.get("found") or json.loads(path.read_bytes()) != desired:
                return None
            if (
                current.email != desired["allowed_email"]
                or current.config_digest != hashlib.sha256(path.read_bytes()).hexdigest()
            ):
                return None
            self.platform.h.discovery.source_command_ready(current)
            return AccessResult.model_validate(receipt["result"]).model_dump()

    def __call__(self, payload):
        with self.platform.lock():
            current, desired, path = self.checked(payload)
            if payload["action"] == "replace_email":
                if any(
                    item.key != current.key
                    and item.email.casefold() == desired["allowed_email"].casefold()
                    for item in self.source.inventory.list()
                ):
                    raise AdminError("admin_operator_email_exists", 409)
                config = self.platform.configuration()

                provider = CloudflareSetup(
                    config["account"], self.platform.provider_token(), config["issuer"]
                )
                observed = provider.verify(current.hostname, desired["allowed_email"])
                if observed is None or observed["audience"] != desired["identity_audience"]:
                    raise AdminError("admin_replacement_provider_setup_required", 409)
            # This command always leaves access inactive and revokes old sessions
            # atomically before publishing the new immutable runtime config.
            result = AccessResult.model_validate(
                self.source._transport(asdict(current), self.source._command(payload).model_dump())
            ).model_dump()
            unit = f"epm-hosted@{current.key}.service"
            self.platform.call(["/usr/bin/systemctl", "stop", unit])
            if self.platform.service_state(current.key) not in {"inactive", "failed"}:
                raise AdminError("admin_containment_pending", 503)
            identity = pwd.getpwnam(current.user)
            if json.loads(path.read_bytes()) != desired:
                self.platform.publish(path, canonical(desired).encode(), identity.pw_gid)
            self.platform.call(["/usr/bin/systemctl", "start", unit])
            observation = self.platform.h.discovery.observe(current.key)
            fields = observation["fields"]
            if any(
                fields[name] != expected
                for name, expected in {
                    "workspace_id": current.workspace_id,
                    "operator_id": current.operator_id,
                    "email": desired["allowed_email"],
                    "port": current.port,
                    "release": current.release,
                }.items()
            ):
                self.platform.call(["/usr/bin/systemctl", "stop", unit])
                raise AdminError("admin_runtime_binding_conflict", 409)
            before = type(current)(**payload["source_reference"]["instance"])
            after = replace(
                before,
                email=desired["allowed_email"],
                config_digest=hashlib.sha256(path.read_bytes()).hexdigest(),
                baseline_digest=self.platform.h.save_baseline(self.source.inventory, observation),
                revision=before.revision + 1,
            )
            self.source.inventory.record_access_cutover(before, after, payload["operation_id"])
            self.platform.h.discovery.source_command_ready(after)
            return result
