"""Root-only host ingress services. No provisioning, admission, start or public HTTP API."""

import argparse
import logging
import sqlite3
from subprocess import SubprocessError
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait
from contextlib import ExitStack
import os
from pathlib import Path
import pwd
import signal
from threading import Event


from app.modules.host_agent.application.dispatch import HostAgentUnavailable, HostAgentDenied
from app.modules.host_agent.infrastructure.docker_engine import DockerEngine
from app.modules.host_agent.infrastructure.gateway import GatewaySettings, CaddyAdmin, closed_config
from app.modules.host_agent.infrastructure.auth_projection import auth_config
from app.modules.host_agent.infrastructure.auth_registration import RegisteredSources
from app.modules.host_agent.infrastructure.host_services import tunnel_config
from app.modules.host_agent.infrastructure.identity_relay import (
    IdentityRelay,
    SourceReturnRelay,
    open_relay_socket,
    serve_identity,
)
from app.modules.host_agent.infrastructure.ingress_bootstrap import (
    IngressBootstrap,
    ProjectionPublisher,
)
from app.modules.host_agent.infrastructure.inventory import Inventory
from app.modules.host_agent.infrastructure.network_firewall import NetworkFirewall
from app.modules.host_agent.infrastructure.network_policy import bridge
from app.modules.host_agent.infrastructure.network_prerequisites import HostNetworkPrerequisites
from app.modules.host_agent.infrastructure.stop_registry import StopRegistry
from app.modules.host_agent.infrastructure.tunnel_credentials import (
    protected_bytes,
    validate_tunnel_credential,
)

from app.modules.host_agent.infrastructure.service_config import (
    IDENTITY_RELAY_DIRECTORY,
    ServiceInputs,
)


def no_allocations():
    # This composition is read-only inventory authority, not the allocator/dispatcher.
    raise HostAgentUnavailable()


def shared_endpoint(sources, snapshot):
    shared, login_origin = sources.resolve_shared()
    if shared is not None:
        origins = {shared.manifest.admin_origin, shared.manifest.central_origin}
        if origins.intersection(row.public_origin for row in snapshot.records):
            raise HostAgentDenied()
    return shared, login_origin


class ServiceRuntime:
    def __init__(self, inputs):
        self.inputs, self.layout = inputs, inputs.layout
        self.engine = DockerEngine()
        self.stops = StopRegistry(Path(self.layout.stops))
        self.firewall = NetworkFirewall(inputs.network)

    def inventory(self):
        return Inventory(
            Path(self.layout.inventory),
            application_directory=Path(self.layout.application),
            identity=self.inputs.metadata,
            uids=self.inputs.uids,
            gids=self.inputs.gids,
            projects=self.inputs.projects,
            public_domain=self.inputs.public_domain,
            system_ids=no_allocations,
        )

    def registered_sources(self, inventory):
        if self.inputs.auth_registration is None:
            return None
        relay = self.inputs.identity_relay
        return RegisteredSources.load(
            inventory,
            self.engine,
            self.firewall,
            self.inputs.network,
            Path(self.inputs.auth_registration),
            Path(self.inputs.identity_socket_root),
            central_principal=(relay.central_uid, relay.central_gid) if relay else None,
        )

    def ingress_projection(self, inventory, snapshot, gateway):
        sources = self.registered_sources(inventory)
        if sources is None:
            return closed_config(snapshot, gateway), tunnel_config(snapshot, self.inputs.tunnel)
        held = tuple(
            (row, sources.resolve_held(row))
            for row in sorted(inventory.auth_ready(), key=lambda item: item.binding_id)
            if row.desired_state == "held"
        )
        try:
            shared, login_origin = shared_endpoint(sources, snapshot)
        except (
            HostAgentDenied,
            HostAgentUnavailable,
            OSError,
            ValueError,
            sqlite3.Error,
            SubprocessError,
        ):
            logging.getLogger(__name__).warning(
                "Shared identity ingress is closed pending native verification."
            )
            shared, login_origin = None, None
        return (
            auth_config(snapshot, gateway, held=held, shared=shared, login_origin=login_origin),
            tunnel_config(snapshot, self.inputs.tunnel, shared=shared.manifest if shared else None),
        )

    def _publish_backup_proxy_inventory(self):
        projection_dir = Path(self.layout.backup_proxy_projection)
        if not projection_dir.is_dir():
            return
        try:
            bp_identity = pwd.getpwnam("epm-backup-proxy")
        except KeyError:
            return
        source_path = Path(self.layout.inventory)
        target_path = projection_dir / "inventory.sqlite"
        staged_path = projection_dir / f".inventory.{os.getpid()}.sqlite.tmp"
        try:
            src_conn = sqlite3.connect(f"{source_path.as_uri()}?mode=ro", uri=True)
            try:
                dst_conn = sqlite3.connect(str(staged_path))
                try:
                    src_conn.backup(dst_conn)
                    dst_conn.execute("PRAGMA journal_mode=DELETE")
                    dst_conn.commit()
                finally:
                    dst_conn.close()
            finally:
                src_conn.close()
            os.chown(staged_path, 0, bp_identity.pw_gid)
            os.chmod(staged_path, 0o640)
            os.replace(staged_path, target_path)
        finally:
            if staged_path.exists():
                staged_path.unlink(missing_ok=True)

    def contain(self):
        self.stops.contain_all(self.engine)

    def serve_relay(self, stopping):
        relay = self.inputs.identity_relay
        if relay is None:
            raise HostAgentDenied()
        sources = self.registered_sources(self.inventory())
        if sources is None:
            raise HostAgentDenied()
        with ExitStack() as stack:
            listener = stack.enter_context(
                open_relay_socket(IDENTITY_RELAY_DIRECTORY, central_gid=relay.central_gid)
            )
            returns = []
            if relay.source_return_directory is not None:
                for binding_id in sorted(sources.entries):
                    row = sources.inventory.auth_target(binding_id=binding_id)
                    path = Path(relay.source_return_directory) / row["operator_id"]
                    source_listener = stack.enter_context(
                        open_relay_socket(path, central_gid=row["host_gid"])
                    )
                    returns.append((source_listener, row))
            workers = stack.enter_context(ThreadPoolExecutor(max_workers=1 + len(returns)))
            try:
                jobs = [
                    workers.submit(
                        serve_identity,
                        listener,
                        IdentityRelay(sources),
                        allowed_uid=relay.central_uid,
                        stopping=stopping,
                    )
                ]
                for endpoint, row in returns:
                    jobs.append(
                        workers.submit(
                            serve_identity,
                            endpoint,
                            SourceReturnRelay(
                                sources,
                                row,
                                Path(relay.central_return_directory),
                                relay.central_uid,
                            ),
                            allowed_uid=row["host_uid"],
                            stopping=stopping,
                            workers=1,
                        )
                    )
                finished, _ = wait(jobs, return_when=FIRST_EXCEPTION)
                for job in finished:
                    job.result()
            finally:
                stopping.set()

    def run(self, action):
        if action == "backup-proxy-projection":
            self._publish_backup_proxy_inventory()
            return
        if action == "verify-shared":
            inventory = self.inventory()
            with inventory.exclusive():
                sources = self.registered_sources(inventory)
                if (
                    sources is None
                    or shared_endpoint(sources, inventory.ingress_projection())[0] is None
                ):
                    raise HostAgentUnavailable()
            return
        try:
            if action == "contain":
                self.contain()
                return
            inventory = self.inventory()
            if action == "network":
                with inventory.exclusive():
                    targets = tuple(
                        bridge(row, self.inputs.network)
                        for row in inventory.network_projection().records
                    )
                    HostNetworkPrerequisites(self.engine, self.inputs.network).verify(targets)
                    self.firewall.apply(targets)
                    shared = self.inputs.network.shared_identity
                    if shared is not None:
                        target = shared.bridge()
                        if self.engine.inspect_network(target.name) is None:
                            self.engine.create_network(target)
                        else:
                            target.verify(self.engine.inspect_network(target.name))
                return
            gateway = GatewaySettings(
                Path(self.layout.gateway_runtime) / "admin.sock",
                self.inputs.network.gateway_uid,
                self.inputs.network.gateway_port,
            )
            if action == "verify":
                with inventory.exclusive():
                    targets = tuple(
                        bridge(row, self.inputs.network)
                        for row in inventory.network_projection().records
                    )
                    self.firewall.verify(targets)
                    candidate, _ = self.ingress_projection(
                        inventory, inventory.ingress_projection(), gateway
                    )
                    if CaddyAdmin(gateway).inspect() != candidate:
                        raise HostAgentUnavailable()
                return
            if action != "refresh":
                raise HostAgentDenied()
            gateway_identity = pwd.getpwnam("epm-caddy")
            tunnel_identity = pwd.getpwnam("epm-tunnel")
            proxy_identity = pwd.getpwnam("epm-proxy")
            if (
                gateway_identity.pw_uid != self.inputs.network.gateway_uid
                or tunnel_identity.pw_uid != self.inputs.network.tunnel_uid
                or proxy_identity.pw_uid != self.inputs.network.proxy_uid
            ):
                raise HostAgentDenied()
            validate_tunnel_credential(
                Path(self.layout.tunnel_secret), self.inputs.tunnel.tunnel_id
            )
            IngressBootstrap(
                inventory,
                gateway,
                self.inputs.tunnel,
                ProjectionPublisher(
                    Path(self.layout.gateway_projection), reader_gid=gateway_identity.pw_gid
                ),
                ProjectionPublisher(
                    Path(self.layout.tunnel_projection), reader_gid=tunnel_identity.pw_gid
                ),
                contain_all=self.contain,
                project_ingress=lambda snapshot: self.ingress_projection(
                    inventory, snapshot, gateway
                ),
            ).refresh()
            ProjectionPublisher(
                Path(self.layout.proxy_projection), reader_gid=proxy_identity.pw_gid
            ).publish(
                {
                    "hosts": self.inputs.outbound_hosts,
                    "port": self.inputs.network.proxy_port,
                    "uid": self.inputs.network.proxy_uid,
                }
            )
            self._publish_backup_proxy_inventory()
        except Exception as original:
            try:
                self.contain()
            except Exception as failure:
                raise ExceptionGroup(
                    "Host ingress requires attention.", [original, failure]
                ) from None
            raise


def load_inputs(path):
    # Protected non-secret setup inputs have an independent 32-KiB bound.
    return ServiceInputs.model_validate_json(protected_bytes(path, limit=32768))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=(
            "network",
            "refresh",
            "verify",
            "verify-shared",
            "contain",
            "relay",
            "backup-proxy-projection",
        ),
    )
    parser.add_argument("--config", type=Path, default=Path("/etc/epm/host-services.json"))
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.exit(3, "The protected host service is unavailable.\n")
    try:
        inputs = load_inputs(args.config)
        if Path(inputs.layout.config) != args.config:
            raise HostAgentDenied()
        runtime = ServiceRuntime(inputs)
        if args.action == "relay":
            stopping = Event()
            for signum in (signal.SIGTERM, signal.SIGINT):
                signal.signal(signum, lambda *_: stopping.set())
            runtime.serve_relay(stopping)
        else:
            runtime.run(args.action)
    except Exception:
        parser.exit(3, "Host ingress requires attention.\n")


if __name__ == "__main__":
    main()
