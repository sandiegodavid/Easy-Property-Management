"""Pure inspection-attention projection shared by inspection and lease reads."""

from __future__ import annotations

from collections.abc import Collection


def inspection_attention(
    *,
    lease_status: str,
    occupancy_starts_on: str,
    actual_move_out_on: str | None,
    finalized_report_kinds: Collection[str],
    effective_on: str,
) -> dict[str, str]:
    """Return the stable inspection attention view from lease and report facts."""
    finalized = set(finalized_report_kinds)
    return {
        "preMoveIn": "complete" if "pre_move_in" in finalized else (
            "overdue" if lease_status == "executed" and occupancy_starts_on < effective_on
            else "due" if lease_status == "executed" else "not_due"
        ),
        "postMoveOut": "complete" if "post_move_out" in finalized else (
            "due" if actual_move_out_on else "not_due"
        ),
    }
