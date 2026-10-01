"""Stable, editable provider-category identities for new workspaces."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderCategorySeed:
    id: str
    display_name: str
    display_order: int
    create_idempotency_key: str

    @property
    def normalized_name(self) -> str:
        return unicodedata.normalize("NFKC", self.display_name).casefold()

    @property
    def create_request_fingerprint(self) -> str:
        return fingerprint(self.display_name, None, self.display_order)


def fingerprint(*values: object) -> str:
    payload = json.dumps(values, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


PROVIDER_CATEGORY_SEEDS = (
    ProviderCategorySeed("00000000-0000-4000-8000-000000000301", "Legal / Attorney", 0, "00000000-0000-4000-8000-000000000300"),
    ProviderCategorySeed("00000000-0000-4000-8000-000000000302", "Landscaping", 1, "00000000-0000-4000-8000-000000000301"),
    ProviderCategorySeed("00000000-0000-4000-8000-000000000303", "Electrical", 2, "00000000-0000-4000-8000-000000000302"),
    ProviderCategorySeed("00000000-0000-4000-8000-000000000304", "HVAC / A/C", 3, "00000000-0000-4000-8000-000000000303"),
    ProviderCategorySeed("00000000-0000-4000-8000-000000000305", "Appliance repair", 4, "00000000-0000-4000-8000-000000000304"),
    ProviderCategorySeed("00000000-0000-4000-8000-000000000306", "Plumbing", 5, "00000000-0000-4000-8000-000000000305"),
    ProviderCategorySeed("00000000-0000-4000-8000-000000000307", "General maintenance", 6, "00000000-0000-4000-8000-000000000306"),
)
