"""Bounded, peer-authenticated transport for the owning source identity API."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
import stat
import struct
from time import monotonic
from typing import Literal

from pydantic import BaseModel, TypeAdapter, model_validator

from app.modules.host_agent.application.dispatch import HostAgentDenied, HostAgentUnavailable
from app.modules.host_agent.infrastructure.unix_transport import MAX_FRAME, _unique_object, peer_uid
from app.modules.hosted_access.application.handoff_channel import (
    ContinuationTarget,
    DestinationObservation,
    HandoffAccepted,
    HandoffRequest,
    LookupIssuance,
    ObserveDestination,
    ObserveRecent,
    RecentChallengeObservation,
    RefreshStatus,
    SignedStatus,
    ReadContinuation,
    ReconcileRevocation,
    AcknowledgeIssuance,
    ReserveHandoff,
    check_reply,
)
from app.modules.hosted_access.application.identity_evidence import SessionReceipt
from app.modules.hosted_access.application.managed_provider import (
    ProviderDenied,
    ProviderUnavailable,
)
from app.modules.hosted_access.application.source_contracts import SourceCommand, SourceResult
from app.platform.hosted_contracts.operations import OperationOutcome, SemanticConflict
from app.platform.hosted_contracts.values import Contract

SOURCE_ACTIONS = frozenset({"claim", "enable", "disable", "rebind", "revoke"})
DEADLINE_SECONDS = 5


class IdentityRelayCall(Contract):
    version: Literal[1] = 1
    method: Literal["execute", "original"]
    command: SourceCommand

    @model_validator(mode="after")
    def identity_only(self):
        if (
            self.command.intent.scope.kind != "workspace"
            or self.command.intent.kind not in SOURCE_ACTIONS
        ):
            raise ValueError("Use a registered workspace identity action.")
        return self


_CALL = TypeAdapter(IdentityRelayCall | HandoffRequest)


def _valid_result(call, result):
    if not isinstance(call, IdentityRelayCall):
        return check_reply(call, result)
    return (result is None and call.method == "original") or (
        isinstance(result, OperationOutcome[SourceResult])
        and result.operation.model_dump(exclude={"operation_id"})
        == call.command.reference().model_dump(exclude={"operation_id"})
    )


def _decode_result(call, raw):
    if raw is None:
        return None
    if isinstance(call, IdentityRelayCall):
        model = OperationOutcome[SourceResult]
    elif isinstance(call, ObserveDestination):
        model = DestinationObservation
    elif isinstance(call, LookupIssuance):
        model = SessionReceipt
    elif isinstance(call, ReadContinuation):
        model = ContinuationTarget
    elif isinstance(call, ObserveRecent):
        model = RecentChallengeObservation
    elif isinstance(call, RefreshStatus):
        model = SignedStatus
    else:
        model = HandoffAccepted
    return model.model_validate_json(json.dumps(raw))


def _budget(connection, deadline):
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise HostAgentUnavailable()
    connection.settimeout(remaining)


def _receive(connection, deadline):
    def read(length):
        data = bytearray()
        while len(data) < length:
            _budget(connection, deadline)
            piece = connection.recv(length - len(data))
            if not piece:
                raise HostAgentUnavailable()
            data.extend(piece)
        return data

    length = struct.unpack("!I", read(4))[0]
    if not 0 < length <= MAX_FRAME:
        raise HostAgentDenied()
    return json.loads(read(length), object_pairs_hook=_unique_object)


def _send(connection, payload, deadline):
    raw = json.dumps(payload, separators=(",", ":")).encode()
    if not 0 < len(raw) <= MAX_FRAME:
        raise HostAgentDenied()
    _budget(connection, deadline)
    connection.sendall(struct.pack("!I", len(raw)) + raw)


def invoke_identity(
    path: Path, call: IdentityRelayCall | HandoffRequest, *, expected_uid: int, deadline=None
):
    if not path.is_absolute() or path.parent.resolve() != path.parent:
        raise HostAgentDenied()
    deadline = (
        min(deadline, monotonic() + DEADLINE_SECONDS)
        if deadline is not None
        else monotonic() + DEADLINE_SECONDS
    )
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            _budget(connection, deadline)
            connection.connect(str(path))
            if peer_uid(connection) != expected_uid:
                raise HostAgentDenied()
            data = call.model_dump(mode="json")
            if isinstance(call, ReserveHandoff):
                data["token"] = call.token.get_secret_value()
            _send(connection, data, deadline)
            reply = _receive(connection, deadline)
        if reply == {"error": "denied"}:
            raise HostAgentDenied()
        if reply == {"error": "conflict"}:
            raise SemanticConflict()
        if not isinstance(reply, dict) or set(reply) != {"result"}:
            raise HostAgentUnavailable()
        result = _decode_result(call, reply["result"])
        if not _valid_result(call, result):
            raise HostAgentUnavailable()
        return result
    except SemanticConflict:
        raise
    except OSError, ValueError, RecursionError:
        raise HostAgentUnavailable() from None


def handle_identity(connection, dispatch, *, allowed_uid: int):
    """Use as either the relay or source listener. Dispatch owns admission and effects."""
    deadline = monotonic() + DEADLINE_SECONDS
    try:
        if peer_uid(connection) != allowed_uid:
            raise HostAgentDenied()
        call = _CALL.validate_python(_receive(connection, deadline))
        result = dispatch(call, deadline=deadline)
        if not _valid_result(call, result):
            raise HostAgentUnavailable()
        response = {
            "result": result.model_dump(mode="json") if isinstance(result, BaseModel) else None
        }
        if isinstance(result, SignedStatus):
            response = {"result": {"signed": result.signed.get_secret_value()}}
    except SemanticConflict:
        response = {"error": "conflict"}
    except HostAgentDenied, ProviderDenied, ValueError, RecursionError:
        response = {"error": "denied"}
    except ProviderUnavailable:
        response = {"error": "unavailable"}
    except Exception:
        response = {"error": "unavailable"}
    _send(connection, response, deadline)


class IdentityRelay:
    """Resolve only an authenticated registration, never a path in a caller payload."""

    def __init__(self, registry):
        self.registry = registry

    def __call__(self, call, *, deadline):
        if isinstance(call, IdentityRelayCall):
            intent = call.command.intent
            endpoint = self.registry.resolve_identity_control(
                intent.deployment_id,
                intent.scope,
                intent.access_epoch,
                original=call.method == "original",
            )
            return invoke_identity(
                endpoint.path, call, expected_uid=endpoint.uid, deadline=deadline
            )
        elif isinstance(call, (ObserveDestination, LookupIssuance, ObserveRecent)):
            intent = call.binding
        else:
            raise HostAgentDenied()
        endpoint = self.registry.resolve_identity_source(
            intent.deployment_id, intent.scope, intent.access_epoch
        )
        return invoke_identity(endpoint.path, call, expected_uid=endpoint.uid, deadline=deadline)


class SourceReturnRelay:
    """Keep each registered Operator on its own UID-bound path to central."""

    def __init__(self, sources, row, central_directory, central_uid):
        self.sources, self.row = sources, row
        self.central_directory, self.central_uid = central_directory, central_uid

    def __call__(self, call, *, deadline):
        if not isinstance(
            call,
            (
                ReadContinuation,
                ReserveHandoff,
                AcknowledgeIssuance,
                RefreshStatus,
                ReconcileRevocation,
            ),
        ):
            raise HostAgentDenied()
        binding = call.binding
        row = self.row
        if (
            binding.scope.operator_id != row["operator_id"]
            or binding.scope.workspace_id != row["workspace_id"]
            or binding.binding_id != row["binding_id"]
            or binding.resource_generation != row["resource_generation"]
            or binding.target_origin != row["public_origin"]
        ):
            raise HostAgentDenied()
        self.sources.resolve_identity_source(
            binding.deployment_id, binding.scope, binding.access_epoch
        )
        return invoke_identity(
            self.central_directory / (binding.scope.operator_id + ".sock"),
            call,
            expected_uid=self.central_uid,
            deadline=deadline,
        )


@contextmanager
def open_relay_socket(directory: Path, *, central_gid: int):
    """Bind inside the service-owned directory without replacing a prior listener."""
    info = directory.lstat()
    if (
        directory.resolve(strict=True) != directory
        or not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.geteuid()
        or info.st_gid != central_gid
        or stat.S_IMODE(info.st_mode) != 0o750
    ):
        raise HostAgentDenied()
    path = directory / "relay.sock"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind(str(path))
        try:
            os.chmod(path, 0o660)
            os.chown(path, -1, central_gid)
            listener.listen(8)
            yield listener
        finally:
            path.unlink(missing_ok=True)


def serve_identity(listener, dispatch, *, allowed_uid: int, stopping, workers=4):
    """Run beside the public listener using the same owning dispatch instance.

    At most one accepted connection per worker. The owning dispatch must honor
    the passed deadline and use the same mutation gate as its public process.
    """
    from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait

    if type(workers) is not int or not 1 <= workers <= 8:
        raise HostAgentDenied()
    if listener.family != socket.AF_UNIX:
        raise HostAgentDenied()
    listener.settimeout(0.2)

    def serve():
        while not stopping.is_set():
            try:
                connection, _ = listener.accept()
            except TimeoutError:
                continue
            with connection:
                try:
                    handle_identity(connection, dispatch, allowed_uid=allowed_uid)
                except OSError, HostAgentDenied, HostAgentUnavailable:
                    # Abandoned or timed out connection. Its owning receipt is
                    # independent of whether this wire response was delivered.
                    continue

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(serve) for _ in range(workers)]
        try:
            done, _ = wait(futures, return_when=FIRST_EXCEPTION)
            for future in done:
                future.result()
        finally:
            stopping.set()


class SourceIdentityDispatch:
    """Adapt a source-owned API to the private listener and its existing mutation gate."""

    def __init__(self, source, authenticate):
        self.source = source
        self.authenticate = authenticate

    def __call__(self, call: IdentityRelayCall, *, deadline):
        from app.modules.hosted_access.application.source_contracts import require_invocation

        if monotonic() >= deadline:
            raise HostAgentUnavailable()
        authority = self.authenticate(call, deadline=deadline)
        require_invocation(authority, call.command)
        if monotonic() >= deadline:
            raise HostAgentUnavailable()
        if call.method == "original":
            return self.source.original(authority, call.command.reference())
        return self.source.execute(authority, call.command)
