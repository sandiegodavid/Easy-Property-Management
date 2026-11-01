"""Installed targets remain ineligible without current exact private qualification."""

from contextlib import nullcontext
from dataclasses import dataclass
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.modules.hosted_admin.infrastructure.upgrade_catalog import InstalledReleaseCatalog


@dataclass(frozen=True)
class Instance:
    profile: str = "profile-two"
    release: str = "release-20261030-01"


@pytest.fixture
def catalog(tmp_path):
    report_id = str(uuid4())
    entry = {
        "target": {
            "release": "release-20261031-01",
            "digest": "a" * 64,
            "installed": 1.0,
            "notes": "Routine release",
            "eligible": True,
            "blockers": [],
            "preserve_sessions": True,
            "compatibility_digest": "b" * 64,
        },
        "profile": "profile-two",
        "operator_ceiling": 2,
        "environment_digest": "c" * 64,
        "observed": 100.0,
        "expires": 400.0,
    }
    instances = [Instance(), Instance()]
    artifact = {"manifest_digest": "a" * 64}
    inventory = SimpleNamespace(get=lambda _: instances[0], list=lambda: instances)
    platform = SimpleNamespace(
        h=SimpleNamespace(
            paths=SimpleNamespace(control=tmp_path, releases=tmp_path),
            inventory=inventory,
            read_json=lambda *_: {"reports": [report_id]},
            discovery=SimpleNamespace(_release=lambda _: artifact),
        ),
        lock=lambda: nullcontext(),
    )
    capacity = SimpleNamespace(environment_hash="c" * 64, observed=100.0, inventory_clear=True)
    reader = InstalledReleaseCatalog(
        platform, SimpleNamespace(report=lambda _: entry), lambda: capacity, lambda: 200.0
    )
    return reader, entry, instances, artifact, capacity


def test_only_exact_installed_qualified_release_is_eligible(catalog):
    reader, _entry, _instances, _artifact, _capacity = catalog
    (choice,) = reader.options("a")
    assert choice.eligible and choice.preserve_sessions and not choice.blockers


@pytest.mark.parametrize(
    "change", ["artifact", "expiry", "profile", "capacity", "count", "already_selected"]
)
def test_ineligible_release_keeps_specific_safe_blocker(catalog, change):
    reader, entry, instances, artifact, capacity = catalog
    if change == "artifact":
        artifact["manifest_digest"] = "d" * 64
    elif change == "expiry":
        entry["observed"], entry["expires"] = 0.0, 100.0
    elif change == "profile":
        entry["profile"] = "another-profile"
    elif change == "capacity":
        capacity.environment_hash = "e" * 64
    elif change == "count":
        instances.append(Instance())
    else:
        entry["target"]["release"] = instances[0].release
    (choice,) = reader.options("a")
    assert not choice.eligible and choice.blockers
    assert str(reader.platform.h.paths.control) not in str(choice.model_dump())


def test_unregistered_target_fails_before_any_mutation(catalog):
    reader, _entry, _instances, _artifact, _capacity = catalog
    with pytest.raises(ValueError, match="admin_upgrade_release_ineligible"):
        reader.prepare("a", "release-20261029-01")


def test_unknown_compatibility_cannot_silently_enable_session_preservation(catalog):
    reader, entry, _instances, _artifact, _capacity = catalog
    del entry["target"]["preserve_sessions"]
    with pytest.raises(ValueError):
        reader.options("a")
