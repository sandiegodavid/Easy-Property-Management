"""GCE OS Login stalled-metadata control in a private network namespace only."""

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
from threading import Thread
import time


def guard():
    if os.geteuid() != 0 or os.environ.get("EPM_H02_QUALIFICATION") != "1":
        raise ValueError("Explicit disposable root Linux qualification is required")


def inside():
    guard()
    if os.readlink("/proc/self/ns/net") == os.readlink("/proc/1/ns/net"):
        raise ValueError("A private network namespace is required")
    links = json.loads(subprocess.check_output(["ip", "-j", "link"], timeout=5))
    if [link["ifname"] for link in links] != ["lo"]:
        raise ValueError("The fixture must have no external network interface")
    subprocess.run(["ip", "link", "set", "lo", "up"], check=True, timeout=5)
    subprocess.run(["ip", "addr", "add", "169.254.169.254/32", "dev", "lo"], check=True, timeout=5)
    requests, clients = [], []
    with socket.socket() as listener:
        listener.bind(("169.254.169.254", 80))
        listener.listen()

        def stalled_metadata():
            while True:
                client, _ = listener.accept()
                clients.append(client)
                # A local blackhole, not a real provider endpoint or credential.
                requests.append(client.recv(4096).split(b"\r\n")[0].decode())

        Thread(target=stalled_metadata, daemon=True).start()
        control = [
            "/usr/bin/python3",
            "-I",
            "-c",
            "import os; print(os.getuid(), os.getgid(), os.getgroups())",
        ]
        results = {}
        for name, arguments, credentials in (
            (
                "setpriv",
                ["setpriv", "--reuid=42011", "--regid=42011", "--clear-groups", *control],
                {},
            ),
            ("numeric_subprocess", control, dict(user=42011, group=42011, extra_groups=[])),
        ):
            start = time.monotonic()
            try:
                result = subprocess.run(
                    arguments, **credentials, capture_output=True, text=True, timeout=5, check=False
                )
                results[name] = dict(returncode=result.returncode, stdout=result.stdout)
            except subprocess.TimeoutExpired:
                results[name] = dict(timeout=True)
            results[name]["elapsed_seconds"] = time.monotonic() - start
        for client in clients:
            client.close()
    if (
        not results["setpriv"].get("timeout")
        or results["numeric_subprocess"].get("returncode") != 0
        or results["numeric_subprocess"].get("stdout", "").strip() != "42011 42011 []"
        or not any("/oslogin/" in request for request in requests)
    ):
        raise AssertionError("Stalled OS Login control or numeric identity proof failed")
    return results | {"metadata_requests": requests}


def run():
    guard()
    root = Path(tempfile.mkdtemp(prefix="epm-principal-qualification-", dir="/var/lib"))
    result = subprocess.run(
        ["unshare", "--net", sys.executable, "-B", str(Path(__file__).resolve()), "--inside"],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    (root / "stdout.log").write_text(result.stdout)
    (root / "stderr.log").write_text(result.stderr)
    result.check_returncode()
    report = json.loads(result.stdout) | {
        "status": "passed",
        "source_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    (root / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(root / "result.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inside", action="store_true")
    args = parser.parse_args()
    if args.inside:
        print(json.dumps(inside()))
    else:
        run()
