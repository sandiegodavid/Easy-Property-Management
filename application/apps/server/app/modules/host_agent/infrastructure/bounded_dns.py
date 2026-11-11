"""Killable DNS lookup. No unbounded executor threads or orphan resolver processes."""

import json
import socket
import subprocess
import sys

from app.modules.host_agent.application.dispatch import HostAgentUnavailable

LOOKUP = """import json,socket,sys
rows=socket.getaddrinfo(sys.argv[1],443,type=socket.SOCK_STREAM)
if len(rows)>16: sys.exit(3)
print(json.dumps(rows))
"""


def resolve(host, port, *, type=socket.SOCK_STREAM):
    if port != 443 or type != socket.SOCK_STREAM:
        raise HostAgentUnavailable()
    try:
        result = subprocess.run(
            [sys.executable, "-I", "-B", "-c", LOOKUP, host],
            capture_output=True,
            timeout=2,
            check=True,
            close_fds=True,
        )
        if len(result.stdout) > 8192:
            raise HostAgentUnavailable()
        return [tuple(row[:4]) + (tuple(row[4]),) for row in json.loads(result.stdout)]
    except (OSError, ValueError, subprocess.SubprocessError) as _error:
        raise HostAgentUnavailable() from None
