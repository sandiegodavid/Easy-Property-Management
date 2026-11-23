"""Manual provisioning and idempotent retry orchestrator for H04.6 (D7/D10)."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from app.modules.host_agent.application.dispatch import HostAgentDenied
from app.modules.hosted_access.application.identity_evidence import IdentityBinding
from app.modules.hosted_access.application.source_contracts import (
    AdmittedFreePolicy,
    InitializeDisabled,
    SourceCommand,
)
from app.modules.hosted_access.infrastructure.source_lifecycle import (
    FREE_V1_USABLE_BYTES,
    SourceLifecycle,
)
from app.modules.hosted_access.infrastructure.usage_accounting import UsageAccountingStore
from app.modules.hosted_admin.infrastructure.provisioning_admission import (
    AdminEffectAdmission,
    ProvisioningIntent,
)
from app.modules.hosted_admin.infrastructure.synthetic_seed import (
    SeedBundleError,
    seed_synthetic_workspace,
)
from app.modules.workspace.application.service import WorkspaceService
from app.platform.config import LocalConfig
from app.platform.hosted_contracts.authority import ServiceAuthority
from app.platform.hosted_contracts.operations import CommandIntent
from app.platform.hosted_contracts.semantic import semantic_hash
from app.platform.hosted_contracts.values import WorkspaceScope
from app.platform.hosted_schema import InitializationResult, initialize_store
from app.platform.schema_resources import HostedStore
from app.platform.sqlite_engine import create_sqlite_engine, immediate_transaction


@dataclass(frozen=True)
class ProvisionOutcome:
    operation_id: str
    operator_id: str
    state: str
    observation_ref: str | None = None
    observed_usage_bytes: int | None = None
    error_code: str | None = None


@dataclass(frozen=True)
class ProvisionPaths:
    workspace_root: Path
    control_root: Path
    scratch_root: Path


HostEffectHook = Callable[[str, ProvisioningIntent, ProvisionPaths], str]


@dataclass(frozen=True)
class ManualProvisionConfig:
    paths_for: Callable[[ProvisioningIntent], ProvisionPaths]
    application_directory: Path
    clock: Callable[[], int]
    dataset_path: Path
    seeder_runner: Callable[[Path, Path, Path], None] | None = None
    host_effect_hook: HostEffectHook | None = None


class ManualProvisioner:
    """Idempotent manual operator workspace provisioner driven by AdminEffectAdmission."""

    def __init__(
        self,
        admission: AdminEffectAdmission,
        config: ManualProvisionConfig,
    ) -> None:
        self.admission = admission
        self.paths_for = config.paths_for
        self.application_directory = config.application_directory
        self.clock = config.clock
        self.dataset_path = config.dataset_path
        self.seeder_runner = config.seeder_runner
        self.host_effect_hook = config.host_effect_hook

    def _start_or_return_succeeded(self, operation_id: str) -> ProvisionOutcome | None:
        try:
            self.admission.mark_running(operation_id)
        except HostAgentDenied:
            refreshed = self.admission.load_provision_intent(operation_id)
            if refreshed.operation_state == "succeeded":
                return ProvisionOutcome(
                    operation_id=operation_id,
                    operator_id=refreshed.operator_id,
                    state="succeeded",
                )
            raise
        return None

    def _prepare_and_seed(self, intent: ProvisioningIntent, paths: ProvisionPaths):
        for directory in (paths.workspace_root, paths.control_root, paths.scratch_root):
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.host_effect_hook is not None:
            self.host_effect_hook("prepare_resources", intent, paths)

        config_path = paths.control_root / "workspace.json"
        ws_service = WorkspaceService(
            LocalConfig(config_path=config_path, workspace_path=paths.workspace_root)
        )
        ws_service.initialize(in_place=True)

        access_path = paths.control_root / "access.sqlite"
        init_result = initialize_store(
            HostedStore.HOSTED_ACCESS,
            access_path,
            application_directory=self.application_directory,
        )
        if init_result not in {
            InitializationResult.INITIALIZED,
            InitializationResult.ALREADY_INITIALIZED,
        }:
            raise RuntimeError("Access store initialization failed.")

        access_engine = create_sqlite_engine(access_path)
        business_engine = create_sqlite_engine(ws_service.paths.database)
        try:
            self._initialize_access_binding(access_engine, intent)
            if intent.initial_data == "synthetic":
                seed_synthetic_workspace(
                    paths.workspace_root,
                    scratch_dir=paths.scratch_root,
                    seed_bundle=intent.seed_bundle,
                    dataset_path=self.dataset_path,
                    seeder_runner=self.seeder_runner,
                )
            usage_store = UsageAccountingStore(access_engine, business_engine, clock=self.clock)
            usage_snap = usage_store.refresh_usage_state()
            if usage_snap.used_bytes >= FREE_V1_USABLE_BYTES:
                raise SeedBundleError(
                    "seed_exceeds_free_allowance",
                    "Initial workspace usage exceeds the Free 50,000,000-byte allowance.",
                )
            return usage_snap
        finally:
            business_engine.dispose()
            access_engine.dispose()

    def _finalize_succeeded(
        self,
        operation_id: str,
        intent: ProvisioningIntent,
        observation_ref: str,
        usage_snap,
    ) -> ProvisionOutcome:
        try:
            self.admission.mark_succeeded(
                operation_id,
                observation_ref=observation_ref,
                observed_usage_bytes=usage_snap.used_bytes,
                observed_at=usage_snap.observed_at,
            )
        except HostAgentDenied:
            refreshed = self.admission.load_provision_intent(operation_id)
            if refreshed.operation_state == "succeeded":
                return ProvisionOutcome(
                    operation_id=operation_id,
                    operator_id=refreshed.operator_id,
                    state="succeeded",
                )
            raise
        except Exception:
            self.admission.mark_needs_attention(
                operation_id,
                error_code="provision_receipt_uncertain",
                summary="Provisioning completion receipt was uncertain; inspect before retry.",
                unknown=True,
            )
            return ProvisionOutcome(
                operation_id=operation_id,
                operator_id=intent.operator_id,
                state="unknown",
                error_code="provision_receipt_uncertain",
            )
        return ProvisionOutcome(
            operation_id=operation_id,
            operator_id=intent.operator_id,
            state="succeeded",
            observation_ref=observation_ref,
            observed_usage_bytes=usage_snap.used_bytes,
        )

    def provision(self, operation_id: str) -> ProvisionOutcome:
        intent = self.admission.load_provision_intent(operation_id)
        if intent.operation_state == "succeeded":
            return ProvisionOutcome(
                operation_id=operation_id,
                operator_id=intent.operator_id,
                state="succeeded",
            )
        already_done = self._start_or_return_succeeded(operation_id)
        if already_done is not None:
            return already_done
        paths = self.paths_for(intent)
        external_effects_started = False
        try:
            usage_snap = self._prepare_and_seed(intent, paths)
            observation_ref = f"provision-receipt:{operation_id}"
            if self.host_effect_hook is not None:
                external_effects_started = True
                self.host_effect_hook("apply_auth_routes", intent, paths)
                observation_ref = self.host_effect_hook("start_container", intent, paths)
        except SeedBundleError as error:
            self.admission.mark_needs_attention(
                operation_id, error_code=error.code, summary=str(error)
            )
            return ProvisionOutcome(
                operation_id=operation_id,
                operator_id=intent.operator_id,
                state="needs_attention",
                error_code=error.code,
            )
        except Exception:
            self.admission.mark_needs_attention(
                operation_id,
                error_code="provision_failed",
                summary="Provisioning interrupted; inspect receipts and retry.",
                unknown=external_effects_started,
            )
            return ProvisionOutcome(
                operation_id=operation_id,
                operator_id=intent.operator_id,
                state="unknown" if external_effects_started else "needs_attention",
                error_code="provision_failed",
            )
        return self._finalize_succeeded(operation_id, intent, observation_ref, usage_snap)

    def _initialize_access_binding(self, access_engine, intent: ProvisioningIntent) -> None:
        binding_id = str(uuid5(NAMESPACE_URL, f"binding:{intent.operator_id}:1"))
        origin_id = str(uuid5(NAMESPACE_URL, f"origin:{intent.operator_id}:1"))
        scope = WorkspaceScope(operator_id=intent.operator_id, workspace_id=intent.workspace_id)
        binding = IdentityBinding(
            deployment_id=intent.deployment_id,
            scope=scope,
            binding_id=binding_id,
            resource_generation=1,
            assignment_revision=1,
            access_epoch=intent.access_epoch,
            registered_origin_id=origin_id,
            issuer=intent.issuer,
            subject="unbound-initial",
            target_origin=intent.public_origin,
        )

        @contextmanager
        def mutation():
            with immediate_transaction(access_engine) as conn:
                yield conn

        lifecycle = SourceLifecycle(
            access_engine, mutation=mutation, binding=lambda: binding, clock=self.clock
        )
        admission_hash = sha256(
            f"{intent.deployment_id}:{intent.policy_id}:{FREE_V1_USABLE_BYTES}".encode()
        ).hexdigest()
        cmd_intent = CommandIntent[InitializeDisabled](
            deployment_id=intent.deployment_id,
            scope=scope,
            kind="initialize_disabled",
            expected_revision=1,
            access_epoch=intent.access_epoch,
            payload=InitializeDisabled(
                binding_id=binding_id,
                policy=AdmittedFreePolicy(
                    policy_id=intent.policy_id,
                    policy_revision=1,
                    usable_bytes=FREE_V1_USABLE_BYTES,
                    admission_hash=admission_hash,
                ),
                assignment_id=intent.component_deployment_id,
            ),
        )
        init_op_id = str(uuid5(NAMESPACE_URL, f"init-binding:{intent.operation_id}"))
        command = SourceCommand(
            operation_id=init_op_id,
            idempotency_key=f"provision-init:{intent.operation_id}",
            intent=cmd_intent,
            request_hash=semantic_hash(cmd_intent),
        )
        actor = ServiceAuthority(
            deployment_id=intent.deployment_id,
            scope=scope,
            service="admin",
            authenticated_channel_ref="host-agent:provision",
        )
        lifecycle.execute(actor, command, email_key=intent.email_key)
