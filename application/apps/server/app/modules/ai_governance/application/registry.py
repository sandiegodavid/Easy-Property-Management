"""Startup-composed static AI definitions.

Later capability slices extend these tuples in code; workspace validation uses
the same objects so recognized historical runs remain restorable.
"""
from app.modules.ai_governance.domain.models import AiActionRegistry, RedactionProfileRegistry
from app.modules.ai_governance.application.service import AiAdapterRegistry

ACTION_REGISTRY = AiActionRegistry()
REDACTION_PROFILE_REGISTRY = RedactionProfileRegistry()
# This is deliberately the same release-owned registry consumed by runtime
# composition and workspace validation.  Future adapter deprecations retain
# their historical definitions here until no supported workspace can reference
# them.
ADAPTER_REGISTRY = AiAdapterRegistry()
# Owning modules add validators alongside non-advisory action definitions.
APPROVAL_EVIDENCE_VALIDATORS = {}
SOURCE_VALIDATORS = {}
