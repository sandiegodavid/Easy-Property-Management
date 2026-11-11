"""Unavailable hosted-access scaffold: no baseline, connection or stamp."""

from app.platform.schema_resources import HostedStore, reject_schema_scaffold

reject_schema_scaffold(HostedStore.HOSTED_ACCESS)
