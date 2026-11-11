"""Explicit synthetic native service fixture; no runtime start or production admission."""

from uuid import uuid4

from sqlalchemy import create_engine

from app.modules.host_agent.application.build_inputs import PrincipalRange
from app.modules.host_agent.application.contracts import PrepareResources
from app.modules.host_agent.application.dispatch import (
    AdmittedEffect,
    HostEffect,
    ResourceInputs,
    ResourcePlan,
    TreeLimits,
)
from app.modules.host_agent.application.effect_contracts import EffectIdentity
from app.modules.host_agent.infrastructure.inventory import Inventory
from app.modules.host_agent.infrastructure.schema_store import HostMetadata, bind_host
from app.platform.hosted_contracts.operations import OperationReference
from app.platform.hosted_contracts.semantic import semantic_hash
from app.platform.hosted_contracts.values import WorkspaceScope
from app.platform.hosted_schema import initialize_store
from app.platform.schema_resources import HostedStore


def initialize(root, application):
    directory = root / "inventory"
    directory.mkdir(mode=0o700)
    path = directory / "inventory.sqlite"
    initialize_store(HostedStore.HOST_INVENTORY, path, application_directory=application)
    metadata = HostMetadata(
        host_id=str(uuid4()),
        deployment_id=str(uuid4()),
        filesystem_identity="synthetic-service-fixture",
        agent_contract_version="host-agent-v1",
        created_at=1,
    )
    engine = create_engine(f"sqlite:///{path}")
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        bind_host(connection, metadata, application_directory=application)
        connection.commit()
    engine.dispose()
    principals = PrincipalRange(first=100000, last=100100)
    projects = PrincipalRange(first=1, last=100)
    inventory = Inventory(
        path,
        application_directory=application,
        identity=metadata,
        uids=principals,
        gids=principals,
        projects=projects,
        public_domain="example.invalid",
        system_ids=lambda: (set(), set()),
    )
    scope = WorkspaceScope(operator_id=str(uuid4()), workspace_id=str(uuid4()))
    reference = OperationReference(
        deployment_id=metadata.deployment_id,
        scope=scope,
        kind="provision",
        operation_id=str(uuid4()),
        idempotency_key="native-services-only",
        request_hash="a" * 64,
    )
    binding = str(uuid4())
    limits = TreeLimits(byte_ceiling=1000000, inode_ceiling=100)
    plan = ResourcePlan(
        image_id=str(uuid4()),
        release_id=str(uuid4()),
        image_digest="b" * 64,
        capacity_profile_ref="native-services-only",
        workspace=limits,
        control=limits,
        scratch=limits,
    )
    inputs = ResourceInputs(plan=plan, public_origin="https://operator.example.invalid")
    command = HostEffect(
        effect=EffectIdentity(
            parent=reference,
            binding_id=binding,
            resource_generation=1,
            kind="prepare_resources",
            slot="native_services_only",
        ),
        access_epoch=1,
        expected_revision=1,
        inputs_hash=semantic_hash(inputs),
        payload=PrepareResources(
            binding_id=binding,
            image_id=plan.image_id,
            release_id=plan.release_id,
            admission_commitment_id=str(uuid4()),
            capacity_profile_ref=plan.capacity_profile_ref,
        ),
    )
    with inventory.exclusive():
        inventory.reserve(
            AdmittedEffect(
                command=command,
                admitted_at=1,
                expires_at=1000,
                plan=plan,
                public_origin=inputs.public_origin,
            ),
            10,
        )
    return path, metadata, principals, projects
