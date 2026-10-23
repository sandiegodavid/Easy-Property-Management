"""Synthetic deployment identity, never a real provider grant."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest


@pytest.fixture
def deployment_values(tmp_path):
    now = datetime.now(UTC)
    return {
        "deployment_mode": "hosted_demo",
        "public_origin": "https://demo-a.example.com",
        "identity_issuer": "https://example.cloudflareaccess.com",
        "identity_audience": "a" * 64,
        "workspace_id": str(uuid4()),
        "operator_id": str(uuid4()),
        "allowed_email": "operator@example.com",
        "administrator_contact": "admin@example.com",
        "administration_database": str(tmp_path / "hosted-access.sqlite"),
        "storage_volume": str(tmp_path / "volume"),
        "storage_image": str(tmp_path / "image.ext4"),
        "enabled_at": now.isoformat(),
        "expires_at": (now + timedelta(days=14)).isoformat(),
        "capabilities": ["records.read", "records.write", "files.read", "files.write"],
    }
