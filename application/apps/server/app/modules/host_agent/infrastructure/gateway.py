"""Caddy deny projection and verified external containment; no enable route in H02."""

from dataclasses import dataclass
from hashlib import sha256
from http.client import HTTPConnection
import json
from pathlib import Path
import socket
import stat

from app.modules.host_agent.application.dispatch import (
    EffectObservation,
    HostAgentDenied,
    HostAgentUnavailable,
)
from app.platform.hosted_contracts.semantic import semantic_hash

MAX_CONFIG = 8 * 1024 * 1024


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


@dataclass(frozen=True)
class GatewaySettings:
    admin_socket: Path
    gateway_uid: int
    port: int = 8080

    def __post_init__(self):
        if (
            not self.admin_socket.is_absolute()
            or ".." in self.admin_socket.parts
            or type(self.gateway_uid) is not int
            or self.gateway_uid <= 0
            or type(self.port) is not int
            or not 1024 <= self.port <= 65535
        ):
            raise HostAgentDenied()


def closed_config(projection, settings):
    routes = []
    for row in projection.records:
        if row.desired_state == "eligible":
            raise HostAgentUnavailable()  # H03 identity/source and positive routing gate.
        host = row.public_origin.removeprefix("https://")
        # Raw hostport equality also rejects alternate ports/trailing dots. Caddy's
        # host matcher alone normalizes a supplied port and is insufficient here.
        match = {
            "header": {"X-Forwarded-Proto": ["https"]},
            "host": [host],
            "expression": '{http.request.hostport} == "' + host + '"',
            "not": [{"header": {"Forwarded": ["*"]}}, {"header": {"X-Forwarded-Host": ["*"]}}],
        }
        response = {
            "handler": "static_response",
            "status_code": 503,
            "headers": {"Cache-Control": ["no-store"], "Content-Type": ["application/json"]},
            "body": '{"code":"workspace_unavailable"}',
        }
        routes.append(
            {
                "@id": "deny-"
                + row.binding_id
                + "-"
                + str(row.access_epoch)
                + "-"
                + row.operation_id,
                "match": [match],
                "handle": [response],
                "terminal": True,
            }
        )
    routes.append(
        {
            "handle": [
                {
                    "handler": "static_response",
                    "status_code": 403,
                    "headers": {"Cache-Control": ["no-store"]},
                    "body": "Request denied.",
                }
            ],
            "terminal": True,
        }
    )
    return {
        "admin": {"listen": "unix/" + str(settings.admin_socket), "config": {"persist": False}},
        "apps": {
            "http": {
                "servers": {
                    "gateway": {
                        "listen": ["127.0.0.1:" + str(settings.port)],
                        "automatic_https": {"disable": True},
                        "routes": routes,
                    }
                }
            }
        },
    }


class AdminConnection(HTTPConnection):
    def __init__(self, path):
        super().__init__("localhost", timeout=5)
        self.path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(str(self.path))


class CaddyAdmin:
    def __init__(self, settings):
        self.settings = settings

    def _request(self, method, path, data=None):
        target = self.settings.admin_socket
        if target.resolve(strict=True) != target:
            raise HostAgentDenied()
        info, parent = target.lstat(), target.parent.stat()
        if (
            not stat.S_ISSOCK(info.st_mode)
            or info.st_uid != self.settings.gateway_uid
            or parent.st_uid != self.settings.gateway_uid
            or stat.S_IMODE(parent.st_mode) & 0o077
            or stat.S_IMODE(info.st_mode) & 0o007
        ):
            raise HostAgentDenied()
        connection = AdminConnection(target)
        try:
            connection.request(
                method,
                path,
                body=encoded(data) if data is not None else None,
                headers={"Content-Type": "application/json", "Cache-Control": "must-revalidate"},
            )
            response = connection.getresponse()
            body = response.read(MAX_CONFIG + 1)
            if response.status != 200 or len(body) > MAX_CONFIG:
                raise HostAgentUnavailable()
            return json.loads(body) if body else None
        finally:
            connection.close()

    def load(self, config):
        if config.get("admin") != {
            "listen": "unix/" + str(self.settings.admin_socket),
            "config": {"persist": False},
        }:
            raise HostAgentDenied()
        self._request("POST", "/load", config)

    def inspect(self):
        return self._request("GET", "/config/")


class Gateway:
    def __init__(
        self,
        inventory,
        admin,
        settings,
        contain,
        *,
        auth_endpoints=None,
        eligible_proof_verifier=None,
    ):
        self.inventory, self.admin, self.settings, self.contain = (
            inventory,
            admin,
            settings,
            contain,
        )

        self.auth_endpoints = auth_endpoints
        self.eligible_proof_verifier = eligible_proof_verifier

    def _snapshot(self, proposed=None):
        snapshot = self.inventory.ingress_projection()
        if self.auth_endpoints is None:
            if proposed is not None:
                raise HostAgentUnavailable()
            return snapshot, closed_config(snapshot, self.settings)

        from app.modules.host_agent.infrastructure.auth_projection import auth_config

        ready = self.inventory.auth_ready()
        if proposed is not None:
            ready = tuple(row for row in ready if row.binding_id != proposed.binding_id)
            ready += (proposed,)
        held = tuple(
            (row, self.auth_endpoints.resolve_held(row))
            for row in sorted(ready, key=lambda item: item.binding_id)
            if row.desired_state == "held"
        )
        eligible = ()
        if hasattr(self.auth_endpoints, "resolve_eligible"):
            eligible_rows = (
                self.inventory.eligible_ready() if hasattr(self.inventory, "eligible_ready") else ()
            )
            eligible = tuple(
                (row, self.auth_endpoints.resolve_eligible(row))
                for row in sorted(eligible_rows, key=lambda item: item.binding_id)
                if row.desired_state == "eligible"
            )
        shared, login_origin = self.auth_endpoints.resolve_shared()
        return snapshot, auth_config(
            snapshot,
            self.settings,
            held=held,
            eligible=eligible,
            shared=shared,
            login_origin=login_origin,
        )

    def auth_effect(self, command, allocation, *, inspect_only=False):
        from app.modules.host_agent.application.auth_routes import AuthRouteObservation

        payload = command.payload
        revision = allocation.ingress_projection_revision
        if (
            revision != payload.expected_ingress_revision + 2
            or allocation.binding_id != command.effect.binding_id
            or allocation.resource_generation != command.effect.resource_generation
            or allocation.access_epoch != command.access_epoch
        ):
            raise HostAgentDenied()
        proposed = AuthRouteObservation(
            binding_id=allocation.binding_id,
            resource_generation=allocation.resource_generation,
            access_epoch=command.access_epoch,
            ingress_revision=revision,
            desired_state="held",
            auth_route_state="ready",
            auth_access_epoch=command.access_epoch,
            auth_manifest_ref=payload.manifest_ref,
            auth_manifest_sha256=payload.manifest_sha256,
            auth_operation_id=command.effect.child_id(),
            auth_verified_at=0,
        )
        if inspect_only:
            _, config = self._snapshot(proposed)
            if self.admin.inspect() != config:
                raise HostAgentUnavailable()
        else:
            try:
                _, config = self._snapshot(proposed)
                self.admin.load(config)
                if self.admin.inspect() != config:
                    raise HostAgentUnavailable()
            except Exception:

                def rollback():
                    try:
                        _, previous = self._snapshot()
                    except Exception:
                        snap = self.inventory.ingress_projection()
                        non_eligible = tuple(
                            row for row in snap.records if row.desired_state != "eligible"
                        )
                        previous = closed_config(
                            snap.model_copy(update={"records": non_eligible}),
                            self.settings,
                        )
                    self.admin.load(previous)

                self._with_containment(command, allocation, rollback)
                raise
        return EffectObservation(
            request_hash=semantic_hash(command),
            binding_id=allocation.binding_id,
            resource_generation=allocation.resource_generation,
            status="applied",
            evidence_ref="gateway-auth-v1:" + sha256(encoded(config)).hexdigest(),
            ingress_state="held",
            ingress_revision=revision,
        )

    def reload_closed(self):
        # Only invoked under the owning inventory singleton. A failed load can
        # retain the old config: never interpret a request result as verified denial.
        _, config = self._snapshot()
        self.admin.load(config)
        if self.admin.inspect() != config:
            raise HostAgentUnavailable()
        return "gateway-deny-v1:" + sha256(encoded(config)).hexdigest()

    def _eligible_verified(self, command) -> bool:
        return (
            self.eligible_proof_verifier is not None
            and bool(getattr(command.payload, "source_identity_proof_ref", None))
            and bool(getattr(command.payload, "resource_readiness_proof_ref", None))
            and self.eligible_proof_verifier(command) is True
        )

    def _eligible_observation_for(self, binding_id: str):
        if not hasattr(self.inventory, "eligible_ready"):
            return None
        for obs in self.inventory.eligible_ready():
            if obs.binding_id == binding_id and obs.workspace_route_state == "ready":
                return obs
        return None

    def _record(self, command, allocation):
        snapshot, config = self._snapshot()
        rows = [row for row in snapshot.records if row.binding_id == allocation.binding_id]
        if len(rows) != 1:
            raise HostAgentDenied()
        row = rows[0]
        scope = command.effect.parent.scope
        allowed_states = {"held", "blocked"}
        if row.desired_state == "eligible":
            if command.effect.kind == "apply_ingress_policy":
                # Ingress admission requires explicit command proof verification (#27, #30).
                obs = self._eligible_observation_for(allocation.binding_id)
                if (
                    self._eligible_verified(command)
                    and obs is not None
                    and obs.source_identity_proof_ref == command.payload.source_identity_proof_ref
                    and obs.resource_readiness_proof_ref
                    == command.payload.resource_readiness_proof_ref
                ):
                    allowed_states.add("eligible")
            else:
                # Runtime-authority verify/supervise on an already-admitted eligible binding (#27).
                if self._eligible_observation_for(allocation.binding_id) is not None:
                    allowed_states.add("eligible")
        if (
            command.effect.binding_id != allocation.binding_id
            or command.effect.resource_generation != allocation.resource_generation
            or row.operator_id != scope.operator_id
            or row.workspace_id != scope.workspace_id
            or row.resource_generation != allocation.resource_generation
            or row.access_epoch != command.access_epoch
            or row.desired_state not in allowed_states
        ):
            raise HostAgentDenied()
        return row, config

    def verify(self, command, allocation):
        _, config = self._record(command, allocation)
        if self.admin.inspect() != config:
            raise HostAgentUnavailable()

    def apply(self, command, allocation):
        if command.effect.kind != "apply_ingress_policy":
            raise HostAgentUnavailable()
        if command.payload.desired_state == "eligible":
            if not self._eligible_verified(command):
                raise HostAgentUnavailable()
            previous = None
            try:
                previous = self.admin.inspect()
            except Exception:
                previous = None
            row, config = self._record(command, allocation)
            if (
                row.operation_id != command.effect.child_id()
                or row.desired_state != "eligible"
                or allocation.ingress_projection_revision is None
            ):
                raise HostAgentDenied()
            try:
                self.admin.load(config)
                if self.admin.inspect() != config:
                    raise HostAgentUnavailable()
            except Exception:
                if previous is not None:
                    try:
                        self.admin.load(previous)
                    except Exception:
                        pass
                raise
            return EffectObservation(
                request_hash=semantic_hash(command),
                binding_id=allocation.binding_id,
                resource_generation=allocation.resource_generation,
                status="applied",
                evidence_ref="gateway-eligible-v1:" + sha256(encoded(config)).hexdigest(),
                ingress_state="eligible",
                ingress_revision=allocation.ingress_projection_revision,
            )

        def apply_closed():
            row, _ = self._record(command, allocation)
            if (
                row.operation_id != command.effect.child_id()
                or row.desired_state != command.payload.desired_state
            ):
                raise HostAgentDenied()
            self.reload_closed()

        self._with_containment(command, allocation, apply_closed)
        return self.inspect(command, allocation)

    def _with_containment(self, command, allocation, operation):
        failures = []
        result = None
        try:
            result = operation()
        except Exception as error:
            failures.append(error)
        # Also contain when authority/config inspection fails. A reload alone
        # cannot establish termination of previously admitted streams.
        try:
            self.contain(command, allocation)
        except Exception as error:
            failures.append(error)
        if failures:
            raise ExceptionGroup("Ingress denial requires attention.", failures)
        return result

    def inspect(self, command, allocation):
        if command.payload.desired_state == "eligible":
            if not self._eligible_verified(command):
                raise HostAgentUnavailable()
            row, config = self._record(command, allocation)
            if (
                row.operation_id != command.effect.child_id()
                or row.desired_state != "eligible"
                or allocation.ingress_projection_revision is None
                or self.admin.inspect() != config
            ):
                raise HostAgentUnavailable()
            return EffectObservation(
                request_hash=semantic_hash(command),
                binding_id=allocation.binding_id,
                resource_generation=allocation.resource_generation,
                status="applied",
                evidence_ref="gateway-eligible-v1:" + sha256(encoded(config)).hexdigest(),
                ingress_state="eligible",
                ingress_revision=allocation.ingress_projection_revision,
            )

        def inspect_closed():
            row, config = self._record(command, allocation)
            if (
                row.operation_id != command.effect.child_id()
                or row.desired_state != command.payload.desired_state
                or allocation.ingress_projection_revision is None
                or self.admin.inspect() != config
            ):
                raise HostAgentUnavailable()
            return row, config

        row, config = self._with_containment(command, allocation, inspect_closed)
        return EffectObservation(
            request_hash=semantic_hash(command),
            binding_id=allocation.binding_id,
            resource_generation=allocation.resource_generation,
            status="applied",
            evidence_ref="gateway-deny-v1:" + sha256(encoded(config)).hexdigest(),
            ingress_state=row.desired_state,
            ingress_revision=allocation.ingress_projection_revision,
        )


class IngressContainment:
    """Stop under the same gate used to publish stop identity before any start.

    A binding with no retained runtime and no start projection is safely not started.
    A start racing denial cannot pass this gate. Corrupt/unavailable stop projections
    fail closed, even if inventory currently has no container ID.
    """

    def __init__(self, registry, engine):
        self.registry, self.engine = registry, engine

    @staticmethod
    def matches(original, command):
        return (
            original.effect.binding_id == command.effect.binding_id
            and original.effect.resource_generation == command.effect.resource_generation
            and original.effect.parent.scope == command.effect.parent.scope
            and original.effect.parent.deployment_id == command.effect.parent.deployment_id
        )

    def __call__(self, command, allocation):
        if (
            command.effect.binding_id != allocation.binding_id
            or command.effect.resource_generation != allocation.resource_generation
        ):
            raise HostAgentDenied()
        failures = []
        stopped = set()
        with self.registry.lock("gate.lock", wait=True):
            for name in self.registry.targets():
                try:
                    target = self.registry.target(name)
                    if self.matches(target.command, command):
                        self.registry.contain(self.engine, target)
                        stopped.add(target.container_id)
                except Exception as error:
                    failures.append(error)
            identity = allocation.container_ref
            if identity is not None and identity not in stopped:
                try:
                    actual = self.engine.inspect(identity)
                    if actual is not None and actual["State"]["Running"]:
                        try:
                            self.engine.stop(identity)
                        except Exception:
                            # Inspect a lost stop response before claiming uncertainty.
                            pass
                        actual = self.engine.inspect(identity)
                    if actual is not None and actual["State"]["Running"] is not False:
                        raise HostAgentUnavailable()
                except Exception as error:
                    failures.append(error)
        if failures:
            raise ExceptionGroup("Ingress runtime containment requires attention.", failures)


class HostEffects:
    """One private effect driver; ingress is never selected through a public route."""

    def __init__(self, runtime, gateway):
        self.runtime, self.gateway = runtime, gateway

    def apply(self, command, allocation):
        if command.effect.kind == "apply_auth_routes":
            return self.gateway.auth_effect(command, allocation)
        if command.effect.kind == "apply_ingress_policy":
            return self.gateway.apply(command, allocation)
        if command.effect.kind == "prepare_resources":
            self.gateway.reload_closed()
        return self.runtime.apply(command, allocation)

    def inspect(self, command, allocation):
        if command.effect.kind == "apply_auth_routes":
            return self.gateway.auth_effect(command, allocation, inspect_only=True)
        if command.effect.kind == "apply_ingress_policy":
            return self.gateway.inspect(command, allocation)
        return self.runtime.inspect(command, allocation)

    def supervise(self, *args, **kwargs):
        return self.runtime.supervise(*args, **kwargs)

    def contain(self, *args, **kwargs):
        return self.runtime.contain(*args, **kwargs)
