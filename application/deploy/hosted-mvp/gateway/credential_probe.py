"""Native systemd credential-consumer probe. Synthetic fixture only; no secret output."""

import errno
import json
import socket
import time
import os
from pathlib import Path
import sys


def denied(operation):
    try:
        operation()
    except OSError as error:
        if error.errno in {errno.EPERM, errno.EACCES, errno.ENOENT, errno.EROFS}:
            return True
        raise
    raise AssertionError("Forbidden credential/data/socket access succeeded")


def main():
    credential = Path(os.environ["CREDENTIALS_DIRECTORY"]) / "tunnel.json"
    value = json.loads(credential.read_bytes())
    assert value["TunnelID"] == sys.argv[1]
    denied(lambda: credential.open("wb"))
    for name in sys.argv[3:]:
        if name.endswith("docker.sock"):
            with socket.socket(socket.AF_UNIX) as engine:
                denied(lambda name=name: engine.connect(name))
        else:
            denied(lambda name=name: Path(name).open("rb"))
    Path(sys.argv[2]).write_text(
        json.dumps(
            {
                "own_credential_readable": True,
                "credential_read_only": True,
                "source_data_and_engine_denied": True,
            }
        )
    )
    time.sleep(30)  # Keep the service credential mount alive for cross-UID probes.


if __name__ == "__main__":
    main()
