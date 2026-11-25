"""Compose peer-authenticated handoff dispatch with its owning process."""

from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
import asyncio
from threading import Event
from time import monotonic

from app.modules.host_agent.application.dispatch import HostAgentDenied, HostAgentUnavailable
from app.modules.host_agent.infrastructure.identity_relay import (
    IdentityRelayCall,
    invoke_identity,
    serve_identity,
)
from app.modules.hosted_access.application.central_login import SourceLoginContext
from app.modules.hosted_access.application.handoff_channel import (
    AcknowledgeIssuance,
    DestinationObservation,
    HandoffAccepted,
    InspectSource,
    LookupIssuance,
    ObserveDestination,
    ObserveRecent,
    RefreshStatus,
    SignedStatus,
    ReadContinuation,
    ReconcileRevocation,
    ReserveHandoff,
)
from app.modules.hosted_access.application.managed_provider import (
    ProviderDenied,
    ProviderUnavailable,
)


def _check_deadline(deadline):
    if monotonic() >= deadline:
        raise ProviderUnavailable()


class DestinationDispatch:
    def __init__(self, owner, *, runtime, lifecycle=None, sessions=None, inspector=None):
        self.owner, self.runtime, self.lifecycle = owner, runtime, lifecycle
        self.sessions = sessions
        self.inspector = inspector

    def __call__(self, request, *, deadline):
        _check_deadline(deadline)
        if not self.runtime.ready or not self.runtime.can_write:
            raise ProviderUnavailable()
        if isinstance(request, IdentityRelayCall) and self.lifecycle is not None:
            return self.lifecycle(request, deadline=deadline)
        if isinstance(request, InspectSource):
            if (
                self.inspector is None
                or self.runtime.workspace_id != request.binding.scope.workspace_id
            ):
                raise ProviderUnavailable()
            return self.inspector(request.binding)
        if not isinstance(request, (ObserveDestination, LookupIssuance, ObserveRecent)):
            raise ProviderDenied()
        if self.runtime.workspace_id != request.binding.scope.workspace_id:
            raise ProviderDenied()
        if isinstance(request, ObserveDestination):
            binding, attempt, renewal = self.owner.observe(request.attempt_id)
            if binding != request.binding:
                raise ProviderDenied()
            return DestinationObservation(binding=binding, attempt=attempt, renewal=renewal)
        if isinstance(request, ObserveRecent):
            if self.sessions is None:
                raise ProviderUnavailable()
            result = self.sessions.observe_recent(request.challenge_id)
            if result.binding != request.binding:
                raise ProviderDenied()
            return result
        return self.owner.observe_receipt(request.receipt)


class CentralHandoffDispatch:
    """Use a single protected source binding per authenticated relay channel."""

    def __init__(self, owner, binding, *, session_authority=None):
        self.owner, self.binding = owner, binding
        self.session_authority = session_authority

    def __call__(self, request, *, deadline):
        _check_deadline(deadline)
        if not isinstance(
            request,
            (
                ReadContinuation,
                ReserveHandoff,
                AcknowledgeIssuance,
                RefreshStatus,
                ReconcileRevocation,
            ),
        ):
            raise ProviderDenied()
        if request.binding != self.binding():
            raise ProviderDenied()
        if isinstance(request, ReadContinuation):
            return self.owner.continuation_target(request.continuation_id, request.binding)
        if isinstance(request, ReconcileRevocation):
            if self.session_authority is None:
                raise ProviderUnavailable()
            self.session_authority.reconcile_revocation(request.binding, request.command)
            return HandoffAccepted()
        if isinstance(request, RefreshStatus):
            if self.session_authority is None:
                raise ProviderUnavailable()
            return SignedStatus(
                signed=self.session_authority.observe(
                    request.binding,
                    request.session_id,
                    request.managed_session_id,
                )
            )
        if isinstance(request, ReserveHandoff):
            self.owner.reserve(request.token, request.grant)
        else:
            self.owner.acknowledge(request.receipt)
        return HandoffAccepted()


def _private_call(path, uid, request, *, deadline=None):
    try:
        return invoke_identity(path, request, expected_uid=uid, deadline=deadline)
    except HostAgentDenied:
        raise ProviderDenied() from None
    except HostAgentUnavailable:
        raise ProviderUnavailable() from None


class SourceBrowserDirectory:
    """Central lookup through protected registration and the Host Agent source relay."""

    def __init__(self, registry, relay_path, *, relay_uid):
        self.registry, self.path, self.uid = registry, relay_path, relay_uid

    def _observe(self, binding, attempt_id):
        result = _private_call(
            self.path,
            self.uid,
            ObserveDestination(binding=binding, attempt_id=attempt_id),
        )
        return result.binding, result.attempt, result.renewal

    def observe(self, operator_id, attempt_id):
        return self._observe(self.registry.by_operator(operator_id), attempt_id)

    def observe_pairing(self, scope, attempt_id):
        binding = self.registry.by_operator(scope.operator_id)
        if binding.scope != scope:
            raise ProviderDenied()
        observed, attempt, _ = self._observe(binding, attempt_id)
        return observed, attempt

    @staticmethod
    def _context(binding, attempt, renewal):
        return SourceLoginContext(
            operator_id=binding.scope.operator_id,
            assignment_revision=binding.assignment_revision,
            access_epoch=binding.access_epoch,
            target_origin=binding.target_origin,
            source_attempt_id=attempt.attempt_id,
            source_browser_hash=attempt.browser_challenge_hash,
            return_path=attempt.return_path,
            expires_at=attempt.expires_at,
            renewal=renewal,
        )

    def resolve_start(self, flow_id, *, origin_id=None):
        if origin_id is None:
            raise ProviderDenied()
        binding = self.registry.by_origin(origin_id)
        if binding.registered_origin_id != origin_id:
            raise ProviderDenied()
        return self._context(*self._observe(binding, flow_id))

    def inspect_start(self, operator_id, source_attempt_id):
        return self._context(*self.observe(operator_id, source_attempt_id))

    def current(self, context):
        if self.inspect_start(context.operator_id, context.source_attempt_id) != context:
            raise ProviderDenied()

    def inspect_source(self, operator_id, workspace_id, access_epoch):
        binding = self.registry.by_operator(operator_id)
        if binding.scope.workspace_id != workspace_id or binding.access_epoch != access_epoch:
            raise ProviderDenied()
        return _private_call(self.path, self.uid, InspectSource(binding=binding))

    def observe_recent(self, binding, challenge_id):
        return _private_call(
            self.path,
            self.uid,
            ObserveRecent(binding=binding, challenge_id=challenge_id),
        )

    def original_control(self, command):
        return _private_call(
            self.path,
            self.uid,
            IdentityRelayCall(method="original", command=command),
        )

    def original(self, receipt):
        return _private_call(self.path, self.uid, LookupIssuance(receipt=receipt))


class BoundCentralRelay:
    """Forward a protected source-specific listener to its configured central peer."""

    def __init__(self, path, uid, binding):
        self.path, self.uid, self.binding = path, uid, binding

    def __call__(self, request, *, deadline):
        if not isinstance(
            request,
            (
                ReadContinuation,
                ReserveHandoff,
                AcknowledgeIssuance,
                RefreshStatus,
                ReconcileRevocation,
            ),
        ):
            raise ProviderDenied()
        if request.binding != self.binding():
            raise ProviderDenied()
        return _private_call(self.path, self.uid, request, deadline=deadline)


class CentralHandoffClient:
    def __init__(self, path, uid, binding):
        self.path, self.uid, self.binding = path, uid, binding

    def _call(self, request):
        return _private_call(self.path, self.uid, request)

    def continuation_target(self, continuation_id):
        return self._call(ReadContinuation(binding=self.binding(), continuation_id=continuation_id))

    def reconcile_revocation(self, command):
        self._call(ReconcileRevocation(binding=self.binding(), command=command))

    def refresh_status(self, binding, session_id, managed_id):
        if binding != self.binding():
            raise ProviderDenied()
        return self._call(
            RefreshStatus(
                binding=binding,
                session_id=session_id,
                managed_session_id=managed_id,
            )
        ).signed

    def reserve(self, token, grant):
        self._call(ReserveHandoff(grant=grant, token=token))

    def acknowledge(self, receipt):
        self._call(AcknowledgeIssuance(receipt=receipt))


@asynccontextmanager
async def own_identity_listener(listener, dispatch, *, peer_uid, workers=4):
    """Listener lifetime nests inside the Operator process's writer ownership."""
    stopping = Event()
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            serve_identity,
            listener,
            dispatch,
            allowed_uid=peer_uid,
            stopping=stopping,
            workers=workers,
        )
        try:
            yield future
        finally:
            stopping.set()
            await asyncio.wrap_future(future)
