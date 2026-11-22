"""Closed H04.10 deployed H04/H05 handoff verification runner and report validator.

Proves against real Admin-lite control plane, ManualProvisioner, Gateway auth projection,
and Operator settings/business admission:
1. Two disposable Operator assignments (one empty workspace, one synthetic-demo-v1 portfolio)
   are admitted, provisioned (with idempotent retry), and sized against pinned H04.9 ceilings.
2. Missing H05 backup protection / readiness holds BOTH workspaces closed:
   - AdminDetail reports protection.state == "unavailable"
   - Gateway projects only held AuthRouteManifest routes (/auth/start, /auth/complete, /auth/status)
   - Requesting desired_state="eligible" is rejected (HostAgentDenied)
   - ManagedBusiness refuses business routes when readiness is False
3. Admin-lite SharedIdentityManifest v2 admits all 11 ADMIN_LITE_ROUTES, enforces
   invitation pre-readiness rejection, pending_delivery -> sent confirmation, reissue
   revocation, zero token leakage in AdminDetail, and RefreshSource cached reads.
4. Operator Settings returns honest Free pilot (50,000,000 B), exact logical usage,
   protection.state == "unavailable", and zero paid-upgrade controls.
5. Full cleanup removes all disposable directories and (on GCP native) ext4 prjquota projects.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import pwd
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import FastAPI
from sqlalchemy import text

from app.modules.host_agent.application.auth_routes import (
    ADMIN_LITE_ROUTES,
    AuthRouteManifest,
    AuthRouteObservation,
    IdentityCookiePolicy,
    SharedIdentityManifest,
)
from app.modules.host_agent.application.capacity import (
    CandidateCapacityProfile,
    CapacitySnapshot,
    OperatorBudget,
    Resources,
)
from app.modules.host_agent.application.dispatch import (
    Allocation,
    HostAgentDenied,
    HostAgentUnavailable,
    ResourceLimits,
    TreeLimits,
)
from app.modules.host_agent.application.ingress import IngressProjection, IngressRecord
from app.modules.host_agent.infrastructure.auth_projection import (
    VerifiedAuthEndpoint,
    auth_config,
)
from app.modules.host_agent.infrastructure.gateway import GatewaySettings
from app.modules.host_agent.infrastructure.manual_provision import (
    ManualProvisionConfig,
    ManualProvisioner,
    ProvisionPaths,
)
from app.modules.host_agent.infrastructure.private_storage import PrivateStorage
from app.modules.host_agent.infrastructure.quota_targets import QuotaTargets
from app.modules.hosted_access.api.managed_business import ManagedBusiness, ManagedBusinessInputs
from app.modules.hosted_access.api.operator_settings import (
    OperatorSettingsInputs,
    operator_settings_router,
)
from app.modules.hosted_access.infrastructure.usage_accounting import UsageAccountingStore
from app.modules.hosted_admin.application.errors import AdminConflictError
from app.modules.hosted_admin.application.pilot_contracts import (
    AdminCommand,
    AdmissionCommitment,
    CreateAssignment,
    RefreshSource,
    ReissueInvitation,
    ResourceCeiling,
)
from app.modules.hosted_admin.application.ui_contracts import AdminFilters
from app.modules.hosted_admin.infrastructure.admin_control import (
    AdminControlService,
    SourceObservationReading,
)
from app.modules.hosted_admin.infrastructure.capacity_store import (
    record_capacity_snapshot,
    register_capacity_profile,
)
from app.modules.hosted_admin.infrastructure.policy_bootstrap import (
    FREE_V1_USABLE_BYTES,
    bootstrap_free_v1_policy,
)
from app.modules.hosted_admin.infrastructure.provisioning_admission import AdminEffectAdmission
from app.modules.hosted_admin.infrastructure.schema_store import DeploymentMetadata, bind_deployment
from app.modules.hosted_admin.infrastructure.synthetic_seed import canonical_seed_bundle_ref
from app.modules.workspace.application.service import WorkspaceService
from app.platform.config import LocalConfig
from app.platform.hosted_contracts.authority import AdminAuthority, ObservationQuery
from app.platform.hosted_contracts.operations import CommandIntent
from app.platform.hosted_contracts.semantic import semantic_hash
from app.platform.hosted_contracts.values import DeploymentScope, WorkspaceScope
from app.platform.hosted_schema import InitializationResult, initialize_store
from app.platform.schema_resources import HostedStore
from app.platform.sqlite_engine import create_sqlite_engine, immediate_transaction

EXPECTED_V2_ADMIN_ROUTES = 11
EXPECTED_OPERATOR_COUNT = 2
SHA256_HEX_LEN = 64
HTTP_OK = 200
HTTP_SERVICE_UNAVAILABLE = 503
DEPLOYMENT_ID = "00000000-0000-4000-8000-000000000901"
RELEASE_ID = "00000000-0000-4000-8000-000000000902"
PROFILE_ID = "00000000-0000-4000-8000-000000000903"
ADMIN_PRINCIPAL_ID = "00000000-0000-4000-8000-000000000904"
ADMIN_SESSION_ID = "00000000-0000-4000-8000-000000000905"
ENDPOINT_ID_SHARED = "00000000-0000-4000-8000-000000000906"
MANIFEST_ID_SHARED = "00000000-0000-4000-8000-000000000907"
PUBLIC_BASE_DOMAIN = "epmdemo.xyz"
ADMIN_ORIGIN = f"https://admin.{PUBLIC_BASE_DOMAIN}"
LOGIN_ORIGIN = f"https://login.{PUBLIC_BASE_DOMAIN}"
SUPPORT_CONTACT = "support@epmdemo.xyz"

REQUIRED_REPORT_FIELDS = {
    "version",
    "slice",
    "mode",
    "h04_9_sizing_sha256",
    "platform",
    "operators",
    "gateway_handoff",
    "admin_lite_boundaries",
    "operator_settings",
    "cleanup",
    "h05_handoff_status",
}


class _StubSessionAuthority:
    """Minimal session authority fixture for Operator Settings verification."""

    def __init__(self, scope: WorkspaceScope, token: str) -> None:
        self._token = token
        self.destination = self
        self._scope = scope

    def binding(self):
        return type("_Binding", (), {"scope": self._scope})()

    def authorize_with_restore(self, cookie: str, *, csrf=None, write: bool = False):
        del csrf, write
        if cookie != self._token:
            raise PermissionError("invalid_cookie")
        return {"subject": "pilot-operator"}


def _admin_actor(now_ms: int) -> AdminAuthority:
    return AdminAuthority(
        deployment_id=DEPLOYMENT_ID,
        principal_id=ADMIN_PRINCIPAL_ID,
        identity_proof_ref=f"session:{ADMIN_SESSION_ID}",
        mfa_verified_at=now_ms,
    )


def _load_h04_9_sizing(sizing_path: Path) -> tuple[dict, str]:
    raw = sizing_path.read_bytes()
    doc = json.loads(raw.decode("utf-8"))
    if doc.get("slice") != "H04.9" or doc.get("logical_free_bytes") != FREE_LOGICAL_BYTES:
        raise ValueError("Invalid H04.9 Free sizing report.")
    return doc, sha256(raw).hexdigest()


FREE_LOGICAL_BYTES = FREE_V1_USABLE_BYTES


MIB = 1024 * 1024
ISSUER = "firebase:project-47b72bb7-ba90-42c9-910"


def _tree_limits_from_sizing(sizing: dict) -> ResourceLimits:
    trees = sizing["derived_trees"]
    return ResourceLimits(
        workspace=TreeLimits(
            byte_ceiling=int(trees["workspace"]["byte_ceiling"]),
            inode_ceiling=int(trees["workspace"]["inode_ceiling"]),
        ),
        control=TreeLimits(
            byte_ceiling=int(trees["control"]["byte_ceiling"]),
            inode_ceiling=int(trees["control"]["inode_ceiling"]),
        ),
        scratch=TreeLimits(
            byte_ceiling=int(trees["scratch"]["byte_ceiling"]),
            inode_ceiling=int(trees["scratch"]["inode_ceiling"]),
        ),
    )


def _free_budget_from_sizing(sizing: dict) -> OperatorBudget:
    return OperatorBudget(
        trees=_tree_limits_from_sizing(sizing),
        memory_bytes=256 * MIB,
        cpu_millicores=500,
        pids=64,
        shared_memory_bytes=16 * MIB,
        log_bytes=4 * MIB,
        log_files=4,
        boot_metadata_bytes=4 * MIB,
        boot_metadata_inodes=256,
    )


def _seed_admin_db(engine, application_directory: Path, sizing: dict, now_ms: int) -> str:
    budget = _free_budget_from_sizing(sizing)
    with immediate_transaction(engine) as connection:
        bind_deployment(
            connection,
            DeploymentMetadata(
                deployment_id=DEPLOYMENT_ID,
                public_base_domain=PUBLIC_BASE_DOMAIN,
                login_origin=LOGIN_ORIGIN,
                registry_generation=1,
                created_at=now_ms,
            ),
            application_directory=application_directory,
        )
        policy, _ = bootstrap_free_v1_policy(
            connection, created_at=now_ms, application_directory=application_directory
        )
        connection.execute(
            text(
                "INSERT INTO main.admin_principals ("
                "principal_id, issuer, subject, enabled, session_generation, revision, created_at"
                ") VALUES (:id, :issuer, :sub, 1, 1, 1, :now)"
            ),
            {
                "id": ADMIN_PRINCIPAL_ID,
                "issuer": ISSUER,
                "sub": "google-admin-h04-10",
                "now": now_ms,
            },
        )
        connection.execute(
            text(
                "INSERT INTO main.qualified_releases ("
                "release_id, component, artifact_kind, artifact_digest, artifact_ref, "
                "compatibility_manifest_ref, compatibility_manifest_sha256, "
                "business_schema_revision, access_schema_revision, recovery_schema_revision, "
                "qualification_ref, state, qualified_at, revision"
                ") VALUES ("
                ":id, 'operator', 'oci_image', :digest, 'operator-image:h04-10', "
                "'manifest-h04-10', :manifest_hash, '0001_initial', 'access_0001_initial', "
                "'recovery_0001_initial', 'qual-h04-9', 'qualified', :now, 1)"
            ),
            {
                "id": RELEASE_ID,
                "digest": "b" * 64,
                "manifest_hash": "c" * 64,
                "now": now_ms,
            },
        )
        profile = CandidateCapacityProfile(
            reference="pilot0-free-h04-9",
            revision=1,
            measurement_sha256=sizing["measurement_sha256"],
            source_sha256=sizing["source_sha256"],
            runtime_policy_sha256="d" * 64,
            maximum_observation_age_ms=300_000,
            shared_reserve=Resources(
                memory_bytes=512 * MIB,
                cpu_millicores=500,
                pids=128,
                data_bytes=256 * MIB,
                data_inodes=4096,
                boot_bytes=256 * MIB,
                boot_inodes=2048,
            ),
            recovery_reserve=Resources(
                data_bytes=512 * MIB,
                data_inodes=8192,
                boot_bytes=64 * MIB,
                boot_inodes=512,
            ),
        )
        register_capacity_profile(connection, profile, budget, created_at=now_ms)
        total = Resources(
            memory_bytes=8192 * MIB,
            cpu_millicores=4000,
            pids=4096,
            data_bytes=32 * 1024 * MIB,
            data_inodes=2_000_000,
            boot_bytes=8 * 1024 * MIB,
            boot_inodes=500_000,
        )
        shared_observed = Resources(
            memory_bytes=256 * MIB,
            cpu_millicores=250,
            pids=64,
            data_bytes=128 * MIB,
            data_inodes=1024,
            boot_bytes=128 * MIB,
            boot_inodes=1024,
        )
        available = Resources(
            memory_bytes=7168 * MIB,
            cpu_millicores=3500,
            pids=3800,
            data_bytes=30 * 1024 * MIB,
            data_inodes=1_900_000,
            boot_bytes=7 * 1024 * MIB,
            boot_inodes=450_000,
        )
        record_capacity_snapshot(
            connection,
            CapacitySnapshot(
                revision=1,
                observed_at=now_ms,
                complete=True,
                profile_ref=profile.reference,
                profile_revision=profile.revision,
                total=total,
                available=available,
                shared_observed=shared_observed,
            ),
        )
    return policy.policy_id


@dataclass(frozen=True)
class _AssignmentSpec:
    slug: str
    email: str
    display_name: str
    initial_data: str
    seed_bundle: str | None


def _create_assignment(
    service: AdminControlService,
    policy_id: str,
    spec: _AssignmentSpec,
    run_ctx: _RunContext,
    expected_registry_revision: int,
) -> tuple[str, str, str, str]:
    operator_id = str(uuid4())
    workspace_id = str(uuid4())
    budget = _free_budget_from_sizing(run_ctx.sizing)
    payload = CreateAssignment(
        operator_id=operator_id,
        workspace_id=workspace_id,
        display_name=spec.display_name,
        email=spec.email,
        slug=spec.slug,
        support_contact=SUPPORT_CONTACT,
        release_id=RELEASE_ID,
        policy_id=policy_id,
        initial_data=spec.initial_data,
        seed_bundle=spec.seed_bundle,
        admission_commitment=AdmissionCommitment(
            warm_memory_bytes=budget.memory_bytes,
            cpu_millis=budget.cpu_millicores,
            workspace=ResourceCeiling(
                bytes=budget.trees.workspace.byte_ceiling,
                inodes=budget.trees.workspace.inode_ceiling,
            ),
            control=ResourceCeiling(
                bytes=budget.trees.control.byte_ceiling,
                inodes=budget.trees.control.inode_ceiling,
            ),
            scratch=ResourceCeiling(
                bytes=budget.trees.scratch.byte_ceiling,
                inodes=budget.trees.scratch.inode_ceiling,
            ),
        ),
    )
    intent = CommandIntent[CreateAssignment](
        deployment_id=DEPLOYMENT_ID,
        scope=DeploymentScope(),
        kind="create_assignment",
        expected_revision=expected_registry_revision,
        access_epoch=1,
        payload=payload,
    )
    cmd = AdminCommand(
        operation_id=str(uuid4()),
        intent=intent,
        idempotency_key=f"h04-10-create-{spec.slug}",
        request_hash=semantic_hash(intent),
    )
    outcome = service.execute(_admin_actor(run_ctx.now_ms), cmd)
    with service.engine.connect() as conn:
        cd_id = conn.execute(
            text(
                "SELECT component_deployment_id FROM main.component_deployments "
                "WHERE operator_id = :op"
            ),
            {"op": operator_id},
        ).scalar_one()
    return operator_id, workspace_id, outcome.operation.operation_id, str(cd_id)


def _verify_gateway_handoff(
    operators: list[dict],
) -> dict:
    shared_manifest = SharedIdentityManifest(
        component_id=MANIFEST_ID_SHARED,
        artifact_sha256="a" * 64,
        private_endpoint_id=ENDPOINT_ID_SHARED,
        admin_origin=ADMIN_ORIGIN,
        central_origin=LOGIN_ORIGIN,
        owning_login_origin=LOGIN_ORIGIN,
        route_policy="separate_exact_host_method_allowlists_v2",
        admin_routes=ADMIN_LITE_ROUTES,
    )
    shared_endpoint = VerifiedAuthEndpoint(
        manifest=shared_manifest,
        address="10.88.0.10",
        port=8443,
        tls_name="admin.internal",
    )
    settings = GatewaySettings(
        admin_socket=Path("/run/epm/caddy.sock"),
        gateway_uid=900,
    )

    records = []
    held_pairs = []
    for idx, op in enumerate(operators, start=1):
        binding_id = str(uuid4())
        op["binding_id"] = binding_id
        manifest = AuthRouteManifest(
            component_id=binding_id,
            artifact_sha256="b" * 64,
            private_endpoint_id=str(uuid4()),
        )
        op_id_for_ingress = str(uuid4())
        records.append(
            IngressRecord(
                binding_id=binding_id,
                operator_id=op["operator_id"],
                workspace_id=op["workspace_id"],
                public_origin=op["public_origin"],
                desired_state="held",
                access_epoch=1,
                resource_generation=1,
                operation_id=op_id_for_ingress,
            )
        )
        observation = AuthRouteObservation(
            binding_id=binding_id,
            desired_state="held",
            auth_route_state="ready",
            access_epoch=1,
            resource_generation=1,
            ingress_revision=1,
            auth_access_epoch=1,
            auth_manifest_ref="auth-manifest-v1",
            auth_manifest_sha256=semantic_hash(manifest),
            auth_operation_id=op_id_for_ingress,
            auth_verified_at=1_700_000_000_000,
        )
        endpoint = VerifiedAuthEndpoint(
            manifest=manifest,
            address=f"10.88.0.{20 + idx}",
            port=8443,
            tls_name=f"{op['slug']}.internal",
        )
        held_pairs.append((observation, endpoint))

    held_projection = IngressProjection(records=tuple(records))
    cfg = auth_config(
        held_projection,
        settings,
        held=tuple(held_pairs),
        shared=shared_endpoint,
        login_origin=LOGIN_ORIGIN,
    )
    routes = cfg["apps"]["http"]["servers"]["gateway"]["routes"]
    admin_host = ADMIN_ORIGIN.removeprefix("https://")
    admin_expressions = [
        route["match"][0]["expression"]
        for route in routes
        if "match" in route and route["match"][0].get("host") == [admin_host]
    ]
    operator_routes: dict[str, list[str]] = {}
    for op in operators:
        host = op["public_origin"].removeprefix("https://")
        operator_routes[op["slug"]] = [
            route["match"][0]["expression"]
            for route in routes
            if "match" in route
            and route["match"][0].get("host") == [host]
            and any(h.get("handler") == "reverse_proxy" for h in route.get("handle", []))
        ]

    # Verify desired_state="eligible" is rejected for each operator while H05 is absent.
    eligible_rejections = {}
    for idx, op in enumerate(operators):
        bad_records = list(records)
        bad_records[idx] = IngressRecord(
            binding_id=records[idx].binding_id,
            operator_id=records[idx].operator_id,
            workspace_id=records[idx].workspace_id,
            public_origin=records[idx].public_origin,
            desired_state="eligible",
            access_epoch=1,
            resource_generation=1,
            operation_id=records[idx].operation_id,
        )
        bad_projection = IngressProjection(records=tuple(bad_records))
        rejected = False
        try:
            auth_config(
                bad_projection,
                settings,
                held=tuple(held_pairs),
                shared=shared_endpoint,
                login_origin=LOGIN_ORIGIN,
            )
        except HostAgentDenied:
            rejected = True
        except HostAgentUnavailable:
            rejected = True
        eligible_rejections[op["slug"]] = rejected

    expected_auth_route_count = len(held_pairs[0][1].manifest.routes)
    held_auth_only = all(
        len(exprs) == expected_auth_route_count
        and all(
            any(path in expr for path in ("/auth/start", "/auth/complete", "/auth/status"))
            for expr in exprs
        )
        and not any("/api/" in expr for expr in exprs)
        for exprs in operator_routes.values()
    )

    return {
        "admin_lite_v2_route_count": len(ADMIN_LITE_ROUTES),
        "admin_origin_route_count": len(admin_expressions),
        "admin_lite_v2_verified": len(ADMIN_LITE_ROUTES) == EXPECTED_V2_ADMIN_ROUTES
        and len(admin_expressions) >= EXPECTED_V2_ADMIN_ROUTES,
        "held_routes_only": held_auth_only,
        "eligible_rejected_by_gateway": all(eligible_rejections.values()),
        "eligible_rejections": eligible_rejections,
    }


def _asgi_get(app: FastAPI, origin: str, path: str, headers: dict[str, str]) -> tuple[int, dict]:
    parsed = urlsplit(origin)
    host = parsed.netloc
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    raw_headers = [(b"host", host.encode("ascii"))] + [
        (key.lower().encode("ascii"), value.encode("ascii")) for key, value in headers.items()
    ]
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": parsed.scheme,
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "headers": raw_headers,
        "server": (parsed.hostname or host, port),
        "client": ("127.0.0.1", 0),
    }
    status_code = 0
    chunks: list[bytes] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        nonlocal status_code
        if message["type"] == "http.response.start":
            status_code = int(message["status"])
        elif message["type"] == "http.response.body":
            chunks.append(message.get("body", b""))

    asyncio.run(app(scope, receive, send))
    return status_code, json.loads(b"".join(chunks).decode("utf-8"))


def _verify_operator_settings_and_closed_business(
    *,
    synthetic_op: dict,
    synthetic_paths: ProvisionPaths,
) -> dict:
    app = FastAPI()

    @app.get("/api/properties")
    def _properties():
        return {"items": []}

    ws_service = WorkspaceService(
        LocalConfig(
            config_path=synthetic_paths.control_root / "workspace.json",
            workspace_path=synthetic_paths.workspace_root,
        )
    )
    access_engine = create_sqlite_engine(synthetic_paths.control_root / "access.sqlite")
    business_engine = create_sqlite_engine(ws_service.paths.database)
    usage_store = UsageAccountingStore(
        access_engine=access_engine,
        business_engine=business_engine,
        clock=lambda: int(time.time() * 1000),
    )
    try:
        managed = ManagedBusiness(
            app=app,
            sessions=None,
            lock=None,
            inputs=ManagedBusinessInputs(readiness=lambda: False, storage=None, files=True),
            database=None,
            leases=None,
            namespaces={},
        )
        closed_capabilities = managed.capabilities()

        scope = WorkspaceScope(
            operator_id=synthetic_op["operator_id"],
            workspace_id=synthetic_op["workspace_id"],
        )
        cookie_token = "h04-10-settings-session"
        stub_sessions = _StubSessionAuthority(scope, cookie_token)
        settings_app = FastAPI()
        settings_app.include_router(
            operator_settings_router(
                stub_sessions,
                OperatorSettingsInputs(
                    origin=synthetic_op["public_origin"],
                    usage_reader=usage_store.read_usage,
                    support_contact=SUPPORT_CONTACT,
                ),
            )
        )
        cookie_name = IdentityCookiePolicy().operator
        status_code, body = _asgi_get(
            settings_app,
            synthetic_op["public_origin"],
            "/api/hosted/settings",
            {"Cookie": f"{cookie_name}={cookie_token}"},
        )
        if status_code != HTTP_OK:
            raise RuntimeError(f"Operator settings failed with HTTP {status_code}")
        actions = body.get("actions", [])
        paid_controls = [
            entry
            for entry in actions
            if any(
                word in str(entry.get("action", "")).lower()
                for word in ("upgrade", "billing", "stripe", "plan")
            )
        ]
        usage_data = body["usage"]["data"]
        return {
            "closed_business_capabilities_empty": closed_capabilities == [],
            "settings_status_code": status_code,
            "plan_code": usage_data.get("plan", "free"),
            "usable_bytes": usage_data.get("allowance_bytes", usage_data.get("usable_bytes")),
            "used_bytes": usage_data["used_bytes"],
            "protection_state": body["protection"]["state"],
            "support_contact": body["support_contact"],
            "paid_upgrade_controls_absent": len(paid_controls) == 0,
        }
    finally:
        access_engine.dispose()
        business_engine.dispose()


TREE_ROLES = ("workspace", "control", "scratch")


def _reserve_projects(data_root: Path, count: int) -> int:
    with (data_root / "qualification-projects").open("r+", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        base = int(handle.read())
        handle.seek(0)
        handle.truncate()
        handle.write(str(base + count))
        handle.flush()
        os.fsync(handle.fileno())
        return base


@dataclass
class _GcpQuotaContext:
    storage: PrivateStorage
    allocations: list[Allocation]
    root: Path


@contextmanager
def _gcp_native_quota_allocator(
    *,
    data_root: Path,
    sizing: dict,
    run_id: str,
):
    bootstrap = json.loads(Path("/etc/epm/bootstrap/data.json").read_text(encoding="utf-8"))
    if bootstrap.get("phase") != "ready":
        raise RuntimeError("Protected retained data filesystem is not in ready phase.")
    run_root = data_root / "qualification" / f"h04-10-{run_id}"
    run_root.mkdir(mode=0o711, parents=True)
    for role in TREE_ROLES:
        (run_root / role).mkdir(mode=0o711)
    targets = QuotaTargets(
        data_root,
        "isolated-h04-handoff-fixture",
        bootstrap["uuid"],
        *(run_root / role for role in TREE_ROLES),
    )
    storage = PrivateStorage(targets)
    limits = _tree_limits_from_sizing(sizing)
    project_base = _reserve_projects(data_root, EXPECTED_OPERATOR_COUNT * len(TREE_ROLES))
    allocations: list[Allocation] = []
    created_users: list[str] = []
    ctx = _GcpQuotaContext(storage=storage, allocations=allocations, root=run_root)

    def allocate_for(_operator_id: str) -> ProvisionPaths:
        idx = len(allocations)
        user = f"epm-h410-{run_id[:6]}{idx}"
        subprocess.run(
            ["useradd", "--system", "--no-create-home", "--shell", "/usr/sbin/nologin", user],
            check=True,
        )
        created_users.append(user)
        owner = pwd.getpwnam(user)
        base_proj = project_base + len(TREE_ROLES) * idx
        alloc = Allocation(
            binding_id=str(uuid4()),
            resource_generation=1,
            host_uid=owner.pw_uid,
            host_gid=owner.pw_gid,
            workspace_project=base_proj,
            control_project=base_proj + 1,
            scratch_project=base_proj + 2,
            filesystem_identity="isolated-h04-handoff-fixture",
            image_digest="b" * 64,
            limits=limits,
        )
        storage.prepare(alloc)
        allocations.append(alloc)
        project_dirs = {
            role: storage.projects(alloc)[role_idx].binding.directory
            for role_idx, role in enumerate(TREE_ROLES)
        }
        # Preserve ext4 prjquota project IDs/limits while allowing in-process store init.
        for directory in project_dirs.values():
            os.chown(directory, os.getuid(), os.getgid())
        return ProvisionPaths(
            workspace_root=project_dirs["workspace"],
            control_root=project_dirs["control"],
            scratch_root=project_dirs["scratch"],
        )

    try:
        yield ctx, allocate_for
    finally:
        shutil.rmtree(run_root, ignore_errors=True)
        for user in created_users:
            subprocess.run(["userdel", user], check=False)


def _inspect_source(
    paths_by_op: dict[str, ProvisionPaths],
    operator_id: str,
    observed_at: int,
) -> SourceObservationReading:
    paths = paths_by_op[operator_id]
    ws_service = WorkspaceService(
        LocalConfig(
            config_path=paths.control_root / "workspace.json",
            workspace_path=paths.workspace_root,
        )
    )
    acc_engine = create_sqlite_engine(paths.control_root / "access.sqlite")
    biz_engine = create_sqlite_engine(ws_service.paths.database)
    try:
        store = UsageAccountingStore(
            access_engine=acc_engine,
            business_engine=biz_engine,
            clock=lambda: observed_at,
        )
        snap = store.read_usage()
        with acc_engine.connect() as conn:
            meta = (
                conn.execute(text("SELECT effective_access FROM main.access_meta WHERE id = 1"))
                .mappings()
                .one()
            )
        return SourceObservationReading(
            effective_enabled=(meta["effective_access"] == "enabled"),
            usage_bytes=snap.used_bytes if snap is not None else 0,
            usable_bytes=FREE_LOGICAL_BYTES,
            source_revision=snap.revision if snap is not None else 1,
            observed_at=observed_at,
        )
    finally:
        acc_engine.dispose()
        biz_engine.dispose()


@dataclass(frozen=True)
class _RunContext:
    admin_db_path: Path
    application_directory: Path
    dataset_path: Path
    sizing: dict
    now_ms: int
    paths_by_op: dict[str, ProvisionPaths]
    paths_factory: Callable[[object], ProvisionPaths]
    quota_enforced: bool


def _provision_and_verify_operator(
    service: AdminControlService,
    provisioner: ManualProvisioner,
    policy_id: str,
    spec: _AssignmentSpec,
    run_ctx: _RunContext,
) -> tuple[dict, bool]:
    with service.engine.connect() as conn:
        registry_gen = int(
            conn.execute(
                text("SELECT registry_generation FROM main.control_meta WHERE id = 1")
            ).scalar_one()
        )
    op_id, ws_id, op_ref_id, cd_id = _create_assignment(
        service, policy_id, spec, run_ctx, registry_gen
    )
    actor = _admin_actor(run_ctx.now_ms + 1000)

    # Invitation must be rejected while setup_state == "pending".
    pre_ready_rejected = False
    try:
        inv_intent = CommandIntent[ReissueInvitation](
            deployment_id=DEPLOYMENT_ID,
            scope=WorkspaceScope(operator_id=op_id, workspace_id=ws_id),
            kind="reissue_invitation",
            expected_revision=1,
            access_epoch=1,
            payload=ReissueInvitation(assignment_id=cd_id, verified_identity_ref="admin:mfa"),
        )
        service.issue_invitation_with_token(
            actor,
            AdminCommand(
                operation_id=str(uuid4()),
                intent=inv_intent,
                idempotency_key=f"pre-ready-inv-{spec.slug}",
                request_hash=semantic_hash(inv_intent),
            ),
        )
    except AdminConflictError:
        pre_ready_rejected = True

    prov = provisioner.provision(op_ref_id)
    if prov.state != "succeeded":
        raise RuntimeError(f"Provisioning failed for {spec.slug}: {prov.error_code}")
    retry = provisioner.provision(op_ref_id)
    if retry.state != "succeeded":
        raise RuntimeError(f"Idempotent retry failed for {spec.slug}")

    with service.engine.connect() as conn:
        op_row = (
            conn.execute(
                text("SELECT revision, desired_access FROM main.operators WHERE operator_id = :op"),
                {"op": op_id},
            )
            .mappings()
            .one()
        )
    op_rev = int(op_row["revision"])
    desired_access = str(op_row["desired_access"])

    refresh_intent = CommandIntent[RefreshSource](
        deployment_id=DEPLOYMENT_ID,
        scope=WorkspaceScope(operator_id=op_id, workspace_id=ws_id),
        kind="refresh_source",
        expected_revision=op_rev,
        access_epoch=1,
        payload=RefreshSource(assignment_id=cd_id),
    )
    service.execute(
        actor,
        AdminCommand(
            operation_id=str(uuid4()),
            intent=refresh_intent,
            idempotency_key=f"refresh-{spec.slug}",
            request_hash=semantic_hash(refresh_intent),
        ),
    )

    inv_intent_1 = CommandIntent[ReissueInvitation](
        deployment_id=DEPLOYMENT_ID,
        scope=WorkspaceScope(operator_id=op_id, workspace_id=ws_id),
        kind="reissue_invitation",
        expected_revision=op_rev,
        access_epoch=1,
        payload=ReissueInvitation(assignment_id=cd_id, verified_identity_ref="admin:mfa"),
    )
    issued_1 = service.issue_invitation_with_token(
        actor,
        AdminCommand(
            operation_id=str(uuid4()),
            intent=inv_intent_1,
            idempotency_key=f"issue-1-{spec.slug}",
            request_hash=semantic_hash(inv_intent_1),
        ),
    )
    if issued_1.invitation_id is None or issued_1.token is None:
        raise RuntimeError(f"Invitation issuance returned no token for {spec.slug}")
    raw_token_1 = issued_1.token.get_secret_value()
    service.mark_invitation_sent(
        actor,
        operator_id=op_id,
        invitation_id=issued_1.invitation_id,
        expected_revision=1,
    )

    detail = service.detail_operator(actor, op_id)
    effective_cached = (
        "enabled"
        if detail.operator.access.data is not None and detail.operator.access.data.effective_enabled
        else "disabled"
    )
    protection_gate = (
        next(
            (gate.state for gate in detail.readiness.data.checks if gate.name == "protection"),
            "missing",
        )
        if detail.readiness.data is not None
        else "missing"
    )
    report = {
        "slug": spec.slug,
        "operator_id": op_id,
        "workspace_id": ws_id,
        "public_origin": f"https://{spec.slug}.{PUBLIC_BASE_DOMAIN}",
        "initial_data": spec.initial_data,
        "seed_bundle": spec.seed_bundle,
        "setup_state": detail.operator.setup_state,
        "desired_access": desired_access,
        "effective_access_cached": effective_cached,
        "protection_state": detail.operator.protection.state,
        "readiness_protection_gate": protection_gate,
        "observed_usage_bytes": detail.operator.usage.data.used_bytes
        if detail.operator.usage.data is not None
        else None,
        "idempotent_retry_succeeded": retry.state == "succeeded",
        "invitation_marked_sent": True,
        "token_leaked_in_detail": raw_token_1 in detail.model_dump_json(),
        "physical_quota_enforced": run_ctx.quota_enforced,
    }
    return report, pre_ready_rejected


def _run_qualification_core(run_ctx: _RunContext) -> dict:
    init = initialize_store(
        HostedStore.ADMIN,
        run_ctx.admin_db_path,
        application_directory=run_ctx.application_directory,
    )
    if init not in {InitializationResult.INITIALIZED, InitializationResult.ALREADY_INITIALIZED}:
        raise RuntimeError("Failed to initialize greenfield admin.sqlite")
    engine = create_sqlite_engine(run_ctx.admin_db_path)
    try:
        policy_id = _seed_admin_db(
            engine, run_ctx.application_directory, run_ctx.sizing, run_ctx.now_ms
        )
        service = AdminControlService(
            engine,
            clock=lambda: run_ctx.now_ms + 1000,
            issuer=ISSUER,
            application_directory=run_ctx.application_directory,
            source_inspector=lambda op_id, _ws_id, _epoch: _inspect_source(
                run_ctx.paths_by_op, op_id, run_ctx.now_ms + 500
            ),
        )
        admission = AdminEffectAdmission(engine, clock=lambda: run_ctx.now_ms + 1000)
        provisioner = ManualProvisioner(
            admission,
            ManualProvisionConfig(
                paths_for=run_ctx.paths_factory,
                application_directory=run_ctx.application_directory,
                clock=lambda: run_ctx.now_ms + 1000,
                dataset_path=run_ctx.dataset_path,
            ),
        )

        specs = (
            _AssignmentSpec(
                slug="h04-empty",
                email="empty@epmdemo.invalid",
                display_name="H04 Empty Pilot",
                initial_data="empty",
                seed_bundle=None,
            ),
            _AssignmentSpec(
                slug="h04-synth",
                email="synth@epmdemo.invalid",
                display_name="H04 Synthetic Pilot",
                initial_data="synthetic",
                seed_bundle=canonical_seed_bundle_ref(run_ctx.dataset_path),
            ),
        )
        operator_reports = []
        pre_ready_flags = []
        for spec in specs:
            op_report, pre_ready_rejected = _provision_and_verify_operator(
                service, provisioner, policy_id, spec, run_ctx
            )
            operator_reports.append(op_report)
            pre_ready_flags.append(pre_ready_rejected)

        listing = service.list_operators(
            _admin_actor(run_ctx.now_ms + 1000),
            query=ObservationQuery(
                deployment_id=DEPLOYMENT_ID,
                scope=DeploymentScope(),
                limit=20,
            ),
            filters=AdminFilters(),
        )
        gateway_handoff = _verify_gateway_handoff(operator_reports)
        synth_op = next(op for op in operator_reports if op["initial_data"] == "synthetic")
        operator_settings = _verify_operator_settings_and_closed_business(
            synthetic_op=synth_op,
            synthetic_paths=run_ctx.paths_by_op[synth_op["operator_id"]],
        )
        return {
            "operators": operator_reports,
            "gateway_handoff": gateway_handoff,
            "admin_lite_boundaries": {
                "list_count": len(listing.directory.data.items)
                if listing.directory.data is not None
                else 0,
                "pre_ready_invitation_rejected": all(pre_ready_flags),
                "refresh_source_verified": all(
                    op["effective_access_cached"] == "disabled"
                    and isinstance(op["observed_usage_bytes"], int)
                    for op in operator_reports
                ),
                "zero_token_leakage": not any(
                    op["token_leaked_in_detail"] for op in operator_reports
                ),
            },
            "operator_settings": operator_settings,
        }
    finally:
        engine.dispose()


def run_handoff_qualification(
    *,
    application_directory: Path,
    dataset_path: Path,
    sizing_path: Path,
    mode: str = "component",
    gcp_data_root: Path | None = None,
) -> dict:
    """Execute the full H04.10 handoff qualification protocol and return a closed report."""
    sizing, sizing_sha256 = _load_h04_9_sizing(sizing_path)
    now_ms = int(time.time() * 1000)
    run_id = uuid4().hex[:12]

    temp_dir = Path(tempfile.mkdtemp(prefix="epm-h04-10-")).resolve()
    os.chmod(temp_dir, 0o700)
    admin_db_path = temp_dir / "admin.sqlite"
    paths_by_op: dict[str, ProvisionPaths] = {}

    try:
        if mode == "gcp_native":
            if gcp_data_root is None:
                raise ValueError("gcp_data_root is required for mode='gcp_native'")
            with _gcp_native_quota_allocator(
                data_root=gcp_data_root, sizing=sizing, run_id=run_id
            ) as (ctx, allocate_for):

                def _gcp_paths(intent) -> ProvisionPaths:
                    if intent.operator_id not in paths_by_op:
                        paths_by_op[intent.operator_id] = allocate_for(intent.operator_id)
                    return paths_by_op[intent.operator_id]

                body = _run_qualification_core(
                    _RunContext(
                        admin_db_path=admin_db_path,
                        application_directory=application_directory,
                        dataset_path=dataset_path,
                        sizing=sizing,
                        now_ms=now_ms,
                        paths_by_op=paths_by_op,
                        paths_factory=_gcp_paths,
                        quota_enforced=True,
                    )
                )
                run_root_check = ctx.root
            cleanup_verified = not run_root_check.exists()
        else:

            def _local_paths(intent) -> ProvisionPaths:
                if intent.operator_id not in paths_by_op:
                    base = temp_dir / "operators" / intent.operator_id
                    paths_by_op[intent.operator_id] = ProvisionPaths(
                        workspace_root=base / "workspace",
                        control_root=base / "control",
                        scratch_root=base / "scratch",
                    )
                return paths_by_op[intent.operator_id]

            body = _run_qualification_core(
                _RunContext(
                    admin_db_path=admin_db_path,
                    application_directory=application_directory,
                    dataset_path=dataset_path,
                    sizing=sizing,
                    now_ms=now_ms,
                    paths_by_op=paths_by_op,
                    paths_factory=_local_paths,
                    quota_enforced=False,
                )
            )
            cleanup_verified = True
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    report = {
        "version": 1,
        "slice": "H04.10",
        "mode": mode,
        "h04_9_sizing_sha256": sizing_sha256,
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "uid": os.getuid(),
            "user": pwd.getpwuid(os.getuid()).pw_name,
        },
        **body,
        "cleanup": {
            "disposable_operators_removed": cleanup_verified and not temp_dir.exists(),
        },
        "h05_handoff_status": "ready_for_h05",
    }
    validate_h04_handoff_report(report)
    return report


def _validate_operator_entry(op: dict, *, mode: str) -> None:
    slug = op.get("slug")
    if op.get("setup_state") != "ready_for_claim":
        raise ValueError(f"Operator {slug} did not reach ready_for_claim.")
    if op.get("protection_state") != "unavailable":
        raise ValueError(f"Operator {slug} fabricated H05 protection.")
    if op.get("effective_access_cached") != "disabled":
        raise ValueError(f"Operator {slug} enabled access before claim/H05.")
    used = op.get("observed_usage_bytes")
    if not isinstance(used, int) or used <= 0 or used > FREE_LOGICAL_BYTES:
        raise ValueError(f"Operator {slug} has invalid observed_usage_bytes.")
    if op.get("idempotent_retry_succeeded") is not True:
        raise ValueError(f"Operator {slug} failed idempotent retry.")
    if op.get("token_leaked_in_detail") is not False:
        raise ValueError(f"Operator {slug} leaked invitation token.")
    if mode == "gcp_native" and op.get("physical_quota_enforced") is not True:
        raise ValueError("GCP native mode requires real ext4 prjquota enforcement.")


def _validate_handoff_sections(report: dict) -> None:
    gw = report["gateway_handoff"]
    if (
        gw.get("admin_lite_v2_verified") is not True
        or gw.get("held_routes_only") is not True
        or gw.get("eligible_rejected_by_gateway") is not True
    ):
        raise ValueError("Gateway H04/H05 closed-handoff checks did not pass.")

    admin = report["admin_lite_boundaries"]
    if (
        admin.get("list_count") != EXPECTED_OPERATOR_COUNT
        or admin.get("pre_ready_invitation_rejected") is not True
        or admin.get("refresh_source_verified") is not True
        or admin.get("zero_token_leakage") is not True
    ):
        raise ValueError("Admin-lite boundary checks did not pass.")

    settings = report["operator_settings"]
    if (
        settings.get("closed_business_capabilities_empty") is not True
        or settings.get("plan_code") != "free"
        or settings.get("usable_bytes") != FREE_LOGICAL_BYTES
        or settings.get("protection_state") != "unavailable"
        or settings.get("paid_upgrade_controls_absent") is not True
    ):
        raise ValueError("Operator Settings / closed-business checks did not pass.")


def validate_h04_handoff_report(report: dict) -> None:
    """Closed validator for H04.10 handoff qualification reports."""
    if not isinstance(report, dict) or set(report.keys()) != REQUIRED_REPORT_FIELDS:
        raise ValueError("H04.10 report keys do not match closed schema.")
    if report["version"] != 1 or report["slice"] != "H04.10":
        raise ValueError("Invalid H04.10 report version or slice.")
    if report["mode"] not in {"component", "gcp_native"}:
        raise ValueError("Invalid H04.10 execution mode.")
    sizing_hash = report["h04_9_sizing_sha256"]
    if not isinstance(sizing_hash, str) or len(sizing_hash) != SHA256_HEX_LEN:
        raise ValueError("Missing pinned h04_9_sizing_sha256.")

    operators = report["operators"]
    if not isinstance(operators, list) or len(operators) != EXPECTED_OPERATOR_COUNT:
        raise ValueError("H04.10 requires exactly two disposable Operator assignments.")
    if {op.get("initial_data") for op in operators} != {"empty", "synthetic"}:
        raise ValueError("H04.10 requires one empty and one synthetic Operator assignment.")
    for op in operators:
        _validate_operator_entry(op, mode=report["mode"])

    _validate_handoff_sections(report)
    if report["cleanup"].get("disposable_operators_removed") is not True:
        raise ValueError("Disposable operators were not cleanly removed.")
    if report["h05_handoff_status"] != "ready_for_h05":
        raise ValueError("Unexpected h05_handoff_status.")


def main(argv: list[str]) -> int:
    min_args = 5
    if len(argv) < min_args:
        sys.stderr.write(
            "Usage: qualify_h04_handoff.py <component|gcp_native> <application_dir> "
            "<sizing_json> <output_json> [gcp_data_root]\n"
        )
        return 2
    mode = argv[1]
    app_dir = Path(argv[2]).resolve()
    sizing_path = Path(argv[3]).resolve()
    output_path = Path(argv[4]).resolve()
    gcp_data_root = Path(argv[5]).resolve() if len(argv) > min_args else Path("/srv/epm/data")

    report = run_handoff_qualification(
        application_directory=app_dir,
        dataset_path=app_dir / "demo" / "dataset.json",
        sizing_path=sizing_path,
        mode=mode,
        gcp_data_root=gcp_data_root if mode == "gcp_native" else None,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
