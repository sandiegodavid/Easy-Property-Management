"""Bounded local Unix Docker API. No shell, TCP engine, image pull or arbitrary endpoint."""

from http.client import HTTPConnection
import json
from pathlib import Path
import re
import socket

from app.modules.host_agent.application.dispatch import HostAgentDenied, HostAgentUnavailable

MAX_RESPONSE = 2 * 1024 * 1024
CONTAINER_ID = re.compile(r"[a-f0-9]{64}\Z")


class UnixConnection(HTTPConnection):
    def __init__(self, path):
        super().__init__("localhost", timeout=20)
        self.path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(str(self.path))


class DockerEngine:
    def __init__(self, socket_path=Path("/var/run/docker.sock")):
        self.socket_path = socket_path

    def _request(self, method, endpoint, data=None, *, missing=False):
        connection = UnixConnection(self.socket_path)
        try:
            connection.request(
                method,
                "/v1.47" + endpoint,
                body=json.dumps(data).encode() if data is not None else None,
                headers={"Content-Type": "application/json"},
            )
            response = connection.getresponse()
            body = response.read(MAX_RESPONSE + 1)
            if len(body) > MAX_RESPONSE:
                raise HostAgentUnavailable()
            if missing and response.status == 404:
                return None
            if response.status not in {200, 201, 204, 304}:
                raise HostAgentUnavailable()
            return json.loads(body) if body else {}
        finally:
            connection.close()

    @staticmethod
    def name(command):
        return "epm-" + command.effect.child_id()

    def inspect(self, identity):
        if not (CONTAINER_ID.fullmatch(identity) or re.fullmatch(r"epm-[a-f0-9-]{36}", identity)):
            raise HostAgentDenied()
        return self._request("GET", "/containers/" + identity + "/json", missing=True)

    def create(self, command, spec):
        result = self._request("POST", "/containers/create?name=" + self.name(command), spec)
        identity = result.get("Id", "")
        if not CONTAINER_ID.fullmatch(identity):
            raise HostAgentUnavailable()
        return identity

    def start(self, identity):
        self._id(identity)
        self._request("POST", "/containers/" + identity + "/start")

    def stop(self, identity):
        self._id(identity)
        self._request("POST", "/containers/" + identity + "/stop?t=10")

    def remove_stopped(self, identity):
        self._id(identity)
        current = self.inspect(identity)
        if current is None or current["State"]["Running"]:
            raise HostAgentDenied()
        self._request("DELETE", "/containers/" + identity + "?force=false&v=false")

    @staticmethod
    def _id(identity):
        if not CONTAINER_ID.fullmatch(identity):
            raise HostAgentDenied()

    @staticmethod
    def _network_name(name):
        if not re.fullmatch(r"epm-n-[a-f0-9-]{36}-[1-9][0-9]{0,18}", name):
            raise HostAgentDenied()

    def inspect_network(self, name):
        self._network_name(name)
        return self._request("GET", "/networks/" + name, missing=True)

    def create_network(self, bridge):
        self._network_name(bridge.name)
        result = self._request("POST", "/networks/create", bridge.spec())
        if not CONTAINER_ID.fullmatch(result.get("Id", "")):
            raise HostAgentUnavailable()
        bridge.verify(self.inspect_network(bridge.name))

    def remove_empty_network(self, name):
        self._network_name(name)
        actual = self.inspect_network(name)
        if actual is None or actual.get("Containers"):
            raise HostAgentDenied()
        self._request("DELETE", "/networks/" + name)

    def networks(self):
        rows = self._request("GET", "/networks")
        if not isinstance(rows, list) or len(rows) > 4096:
            raise HostAgentUnavailable()
        return rows
