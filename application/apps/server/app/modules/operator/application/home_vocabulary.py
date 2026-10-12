"""Stable discriminators shared by Home schemas and registration."""

from enum import StrEnum


class Collection(StrEnum):
    NEEDS_ACTION = "needs_action"
    WAITING = "waiting"
    UPCOMING = "upcoming"
    APPOINTMENTS = "appointments"
    INFORMATION_REVIEW = "information_review"


class SourceKind(StrEnum):
    TASK = "task"
    RENT = "rent_expectation"
    ISSUE = "maintenance_issue"
    REPORT = "owner_rent_report"
    CONCERN = "owner_concern"
    LEASE = "lease"
    APPOINTMENT = "maintenance_appointment"
    COVERAGE = "coverage"
