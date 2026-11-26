"""Exercise Pilot 0 add-operator wizard guards and validators without touching GCP."""

from pathlib import Path
import shlex
import subprocess

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
WIZARD = "epm-pilot0-add-operator.sh"


def functions():
    return (SCRIPTS / WIZARD).read_text().rsplit('\nmain "$@"', 1)[0]


def shell(body: str):
    return subprocess.run(
        ["bash", "-c", functions() + "\n" + body],
        capture_output=True,
        text=True,
        check=False,
    )


def test_syntax_help_and_noninteractive_guard():
    script = SCRIPTS / WIZARD
    subprocess.run(["bash", "-n", str(script)], check=True)

    help_res = subprocess.run(
        ["bash", str(script), "--help"], capture_output=True, text=True, check=False
    )
    assert help_res.returncode == 0
    assert "Usage:" in help_res.stdout
    assert "pilot0-admission-and-incidents.md" in help_res.stdout

    non_tty = subprocess.run(["bash", str(script)], capture_output=True, text=True, check=False)
    assert non_tty.returncode != 0
    assert "Stopped:" in non_tty.stderr


@pytest.mark.parametrize(
    "value",
    [
        "a24bac0e-3f7f-5064-a5e5-f7b6efcec645",
        "00000000-0000-4000-8000-000020261125",
    ],
)
def test_valid_uuid_accepts_canonical_uuids(value):
    assert shell(f"valid_uuid {shlex.quote(value)}").returncode == 0


@pytest.mark.parametrize(
    "value", ["", "not-a-uuid", "A24BAC0E-3F7F-5064-A5E5-F7B6EFCEC645", "a;id"]
)
def test_valid_uuid_rejects_invalid_values(value):
    assert shell(f"valid_uuid {shlex.quote(value)}").returncode != 0


@pytest.mark.parametrize("value", ["demo-a", "demo-c", "wwjdf", "op1"])
def test_valid_slug_accepts_operator_slugs(value):
    assert shell(f"valid_slug {shlex.quote(value)}").returncode == 0


@pytest.mark.parametrize(
    "value", ["admin", "login", "-bad", "bad-", "BadSlug", "a_b", "a/b", "a;touch bad"]
)
def test_valid_slug_rejects_reserved_and_invalid_slugs(value):
    assert shell(f"valid_slug {shlex.quote(value)}").returncode != 0


@pytest.mark.parametrize("value", ["100000", "100001", "100025", "999999"])
def test_valid_host_uid_accepts_allocated_range(value):
    assert shell(f"valid_host_uid {shlex.quote(value)}").returncode == 0


@pytest.mark.parametrize("value", ["0", "65532", "99999", "1000000", "abc", "100001;id"])
def test_valid_host_uid_rejects_out_of_range_and_non_numeric(value):
    assert shell(f"valid_host_uid {shlex.quote(value)}").returncode != 0


@pytest.mark.parametrize(
    "value",
    [
        "sha256:488f0d831501c2c44527adf0aa6324365d009e234d501922d685d225578eb5bd",
        "epm-pilot0-operator:pilot0-20261125-ui",
    ],
)
def test_valid_image_ref_accepts_digest_and_tag(value):
    assert shell(f"valid_image_ref {shlex.quote(value)}").returncode == 0


@pytest.mark.parametrize("value", ["", "has space", "bad;rm -rf /", "line1\nline2"])
def test_valid_image_ref_rejects_shell_unsafe_values(value):
    assert shell(f"valid_image_ref {shlex.quote(value)}").returncode != 0


@pytest.mark.parametrize("value", ["empty", "synthetic"])
def test_valid_workspace_mode_accepts_documented_modes(value):
    assert shell(f"valid_workspace_mode {shlex.quote(value)}").returncode == 0


@pytest.mark.parametrize("value", ["", "demo", "full", "empty;id"])
def test_valid_workspace_mode_rejects_unknown_modes(value):
    assert shell(f"valid_workspace_mode {shlex.quote(value)}").returncode != 0
