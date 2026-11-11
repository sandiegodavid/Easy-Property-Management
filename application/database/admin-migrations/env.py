"""Owning current-schema runner; no URL/default-engine or stamp fallback."""

from app.platform.hosted_schema import run_resource_environment
from app.platform.schema_resources import HostedStore

run_resource_environment(HostedStore.ADMIN)
