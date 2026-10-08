"""Portfolio-owned inventory command identities and immutable receipts."""

from dataclasses import dataclass
from hashlib import sha256
from json import dumps
from typing import Literal

from app.modules.portfolio.application.ports import PropertyView

InventoryAction = Literal[
    "create_property",
    "patch_property",
    "archive_property",
    "restore_property",
    "replace_ownerships",
    "add_space",
    "patch_space",
    "archive_space",
    "restore_space",
]
INVENTORY_ACTIONS = frozenset(InventoryAction.__args__)


def canonical_json(value: object) -> str:
    return dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def fingerprint(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class InventoryCommand:
    action: InventoryAction
    target_id: str | None
    expected_revision: int
    idempotency_key: str
    payload: dict[str, object]

    def request_json(self) -> str:
        return canonical_json(
            {
                "action": self.action,
                "targetId": self.target_id,
                "expectedPropertyRevision": self.expected_revision,
                "payload": self.payload,
            }
        )


def receipt_audit(receipt: dict[str, object]) -> dict[str, object]:
    return {
        key: value for key, value in receipt.items() if key not in {"request_json", "response_json"}
    }


def inventory_state(raw: PropertyView) -> dict[str, object]:
    """Inventory facts only; independent status writers own Space revision/time."""
    property, ownerships, _, spaces = raw
    return {
        "property": property.to_dict(),
        "ownerships": sorted((item.to_dict() for item in ownerships), key=lambda item: item["id"]),
        "spaces": sorted(
            (
                {
                    "normalizedName": item.normalized_name,
                    "archivedByPropertyOperationId": item.archived_by_property_operation_id,
                    **{
                        key: value
                        for key, value in item.to_dict().items()
                        if key not in {"revision", "updatedAt"}
                    },
                }
                for item in spaces
            ),
            key=lambda item: item["id"],
        ),
    }
