"""Exercise only local launcher shims, never cloud, SSH, browser or host resources."""

import os
from pathlib import Path
import subprocess

import pytest

LAUNCHER = Path(__file__).resolve().parents[1] / "epm-admin-mac.sh"
INVALID_ARGUMENTS = 2


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["p", "z", "v", "80"],
        ["p", "z", "v", "999999999999999999999"],
        ["p", "z", "--command", "8765"],
    ],
)
def test_invalid_installation_selectors_fail_before_cloud(args):
    result = subprocess.run(["bash", str(LAUNCHER), *args], capture_output=True, check=False)
    assert result.returncode == INVALID_ARGUMENTS


def test_launcher_waits_for_private_origin_and_opens_without_credential_in_url(tmp_path):
    tools = tmp_path / "bin"
    tools.mkdir()
    log = tmp_path / "calls"
    fixtures = {
        "gcloud": (
            '#!/bin/bash\nprintf "cloud %s\\n" "$*" >> "$CALL_LOG"\n'
            'printf "synthetic-one-use-credential\\n"\n/bin/sleep 1\n'
        ),
        "curl": '#!/bin/bash\nprintf "probe %s\\n" "$*" >> "$CALL_LOG"\n',
        "open": '#!/bin/bash\nprintf "open %s\\n" "$*" >> "$CALL_LOG"\n',
    }
    for name, content in fixtures.items():
        path = tools / name
        path.write_text(content)
        path.chmod(0o700)
    result = subprocess.run(
        ["bash", str(LAUNCHER), "project", "zone", "vm", "8765"],
        env=os.environ | {"PATH": f"{tools}:/usr/bin:/bin", "CALL_LOG": str(log)},
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 0
    calls = log.read_text().splitlines()
    assert any("-L127.0.0.1:8765:127.0.0.1:8765" in call for call in calls)
    assert any("-oExitOnForwardFailure=yes" in call for call in calls)
    assert calls[-1] == "open http://epm-admin.localhost:8765/"
    assert "synthetic-one-use-credential" not in log.read_text()
    assert "synthetic-one-use-credential" in result.stdout
