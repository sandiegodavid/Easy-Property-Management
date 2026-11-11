"""Bounded HTTPS CONNECT relay; no URL fetcher, TLS termination or credential store."""

from dataclasses import dataclass
import select
import socket
from socketserver import StreamRequestHandler, ThreadingTCPServer
from threading import BoundedSemaphore, Lock
import time

from app.modules.host_agent.application.dispatch import HostAgentDenied
from app.modules.host_agent.infrastructure.tls_hello import read_client_hello

MAX_HEADERS = 16384
MAX_LINE = 4096
MAX_TUNNEL_SECONDS = 300


def authority_from_request(stream):
    first = stream.readline(MAX_LINE + 1)
    if len(first) > MAX_LINE or not first.endswith(b"\r\n"):
        raise HostAgentDenied()
    try:
        method, authority, version = first.decode("ascii").strip().split(" ")
    except (UnicodeError, ValueError) as error:
        raise HostAgentDenied() from error
    if method != "CONNECT" or version != "HTTP/1.1":
        raise HostAgentDenied()
    size = len(first)
    headers = {}
    while True:
        line = stream.readline(MAX_LINE + 1)
        size += len(line)
        if len(line) > MAX_LINE or size > MAX_HEADERS or not line.endswith(b"\r\n"):
            raise HostAgentDenied()
        if line == b"\r\n":
            break
        try:
            key, value = line.decode("ascii").rstrip("\r\n").split(":", 1)
        except (UnicodeError, ValueError) as error:
            raise HostAgentDenied() from error
        key = key.lower()
        if key in headers or key not in {"host", "user-agent", "proxy-connection"}:
            raise HostAgentDenied()
        headers[key] = value.strip()
    if headers.get("host") != authority:
        raise HostAgentDenied()
    return authority


def connect_numeric(endpoints):
    last = None
    deadline = time.monotonic() + 5
    for family, address in endpoints:
        if time.monotonic() >= deadline:
            break
        upstream = socket.socket(family, socket.SOCK_STREAM)
        upstream.settimeout(max(0.01, deadline - time.monotonic()))
        try:
            upstream.connect(address)
            return upstream
        except OSError as error:
            last = error
            upstream.close()
    raise HostAgentDenied() from last


def relay(client, upstream, *, seconds=MAX_TUNNEL_SECONDS):
    deadline = time.monotonic() + seconds
    peers = {client: upstream, upstream: client}
    while time.monotonic() < deadline:
        readable, _, _ = select.select(
            list(peers), [], [], min(5, max(0, deadline - time.monotonic()))
        )
        for source in readable:
            chunk = source.recv(65536)
            if not chunk:
                return
            peers[source].sendall(chunk)


@dataclass(frozen=True)
class ProxyApplication:
    policy: object

    def serve(self, client, stream):
        authority = authority_from_request(stream)
        endpoints = self.policy.resolve(authority)
        client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        try:
            hello = read_client_hello(client, authority.rsplit(":", 1)[0])
            with connect_numeric(endpoints) as upstream:
                upstream.sendall(hello)
                relay(client, upstream)
        except Exception:
            # Once CONNECT is accepted, close on any TLS/connect/relay failure;
            # never inject a second HTTP response into the client's TLS stream.
            return


class ProxyServer(ThreadingTCPServer):
    daemon_threads = False
    # Allows a supervised restart across TIME_WAIT; SO_REUSEPORT remains disabled,
    # so a second live listener cannot share the address.
    allow_reuse_address = True
    request_queue_size = 32

    def __init__(self, address, policy):
        self.application = ProxyApplication(policy)
        self.capacity = BoundedSemaphore(32)
        self.clients = set()
        self.clients_lock = Lock()
        super().__init__(address, ProxyHandler)

    def process_request(self, request, client_address):
        if not self.capacity.acquire(blocking=False):
            self.shutdown_request(request)
            return
        with self.clients_lock:
            self.clients.add(request)
        try:
            super().process_request(request, client_address)
        except Exception:
            with self.clients_lock:
                self.clients.discard(request)
            self.capacity.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            with self.clients_lock:
                self.clients.discard(request)
            self.capacity.release()

    def server_close(self):
        with self.clients_lock:
            for client in self.clients:
                try:
                    client.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                client.close()
        super().server_close()


class ProxyHandler(StreamRequestHandler):
    # Unbuffered headers avoid swallowing early TLS bytes that belong to the relay.
    rbufsize = 0

    def handle(self):
        self.request.settimeout(10)
        try:
            self.server.application.serve(self.request, DeadlineLines(self.request))
        except Exception:
            try:
                self.request.sendall(
                    b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\nContent-Length: 0\r\n\r\n"
                )
            except OSError:
                pass


class DeadlineLines:
    def __init__(self, client):
        self.client, self.deadline = client, time.monotonic() + 10

    def readline(self, limit):
        data = bytearray()
        while len(data) < limit:
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise HostAgentDenied()
            self.client.settimeout(remaining)
            value = self.client.recv(1)
            if not value:
                break
            data.extend(value)
            if value == b"\n":
                break
        return bytes(data)


def proxy_policy(path):
    import json
    import os
    import stat
    from app.modules.host_agent.infrastructure.endpoint_policy import EndpointPolicy

    info, parent = path.lstat(), path.parent.stat()
    if (
        path.resolve(strict=True) != path
        or not stat.S_ISREG(info.st_mode)
        or info.st_uid != 0
        or info.st_nlink != 1
        or stat.S_IMODE(info.st_mode) != 0o640
        or parent.st_uid != 0
        or stat.S_IMODE(parent.st_mode) != 0o750
        or info.st_size > 16384
    ):
        raise HostAgentDenied()
    value = json.loads(path.read_bytes())
    if set(value) != {"hosts", "port", "uid"} or value["uid"] != os.geteuid():
        raise HostAgentDenied()
    if type(value["port"]) is not int or not 1024 <= value["port"] <= 65535:
        raise HostAgentDenied()
    return EndpointPolicy(tuple(value["hosts"])), value["port"]


def main():
    import argparse
    from pathlib import Path
    import signal
    from threading import Event, Thread

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, required=True)
    args = parser.parse_args()
    try:
        policy, port = proxy_policy(args.policy)
        stopped = Event()
        for signum in (signal.SIGTERM, signal.SIGINT):
            signal.signal(signum, lambda *args: stopped.set())
        with ProxyServer(("0.0.0.0", port), policy) as server:
            thread = Thread(target=lambda: server.serve_forever(poll_interval=0.1))
            thread.start()
            try:
                stopped.wait()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)
    except Exception:
        parser.exit(3, "The protected outbound service is unavailable.\n")


if __name__ == "__main__":
    main()
