"""Bounded TLS ClientHello/SNI admission, not TLS termination or HTTP inspection."""

import time

from app.modules.host_agent.application.dispatch import HostAgentDenied

MAX_HELLO = 32768


class Fields:
    def __init__(self, data):
        self.data, self.offset = data, 0

    def take(self, size):
        value = self.data[self.offset : self.offset + size]
        if len(value) != size:
            raise HostAgentDenied()
        self.offset += size
        return value

    def vector(self, length_bytes):
        return self.take(int.from_bytes(self.take(length_bytes), "big"))


def server_name(hello):
    fields = Fields(hello)
    if fields.take(2) != b"\x03\x03":
        raise HostAgentDenied()
    fields.take(32)
    if len(fields.vector(1)) > 32:
        raise HostAgentDenied()
    ciphers = fields.vector(2)
    if not ciphers or len(ciphers) % 2 or fields.vector(1) != b"\0":
        raise HostAgentDenied()
    extensions = Fields(fields.vector(2))
    if fields.offset != len(fields.data):
        raise HostAgentDenied()
    seen, name = set(), None
    while extensions.offset < len(extensions.data):
        kind = int.from_bytes(extensions.take(2), "big")
        value = extensions.vector(2)
        if kind in seen or kind == 0xFE0D:  # ECH must not hide the admitted endpoint name.
            raise HostAgentDenied()
        seen.add(kind)
        if kind == 0:
            names = Fields(value)
            entry = Fields(names.vector(2))
            if names.offset != len(value) or entry.take(1) != b"\0":
                raise HostAgentDenied()
            name = entry.vector(2).decode("ascii")
            if entry.offset != len(entry.data):
                raise HostAgentDenied()
    if name is None:
        raise HostAgentDenied()
    return name


def read_client_hello(client, host):
    deadline = time.monotonic() + 5
    records, handshake = bytearray(), bytearray()

    def read(size):
        result = bytearray()
        while len(result) < size:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise HostAgentDenied()
            client.settimeout(remaining)
            part = client.recv(size - len(result))
            if not part:
                raise HostAgentDenied()
            result.extend(part)
        return bytes(result)

    while len(records) <= MAX_HELLO:
        header = read(5)
        size = int.from_bytes(header[3:5], "big")
        if (
            header[0] != 22
            or header[1:3] not in {b"\x03\x01", b"\x03\x03"}
            or not 0 < size <= 16384
        ):
            raise HostAgentDenied()
        if len(records) + size + 5 > MAX_HELLO:
            raise HostAgentDenied()
        payload = read(size)
        records.extend(header + payload)
        handshake.extend(payload)
        if len(handshake) < 4:
            continue
        length = int.from_bytes(handshake[1:4], "big")
        if handshake[0] != 1 or length > MAX_HELLO - 4:
            raise HostAgentDenied()
        if len(handshake) >= length + 4:
            if server_name(handshake[4 : 4 + length]) != host:
                raise HostAgentDenied()
            client.settimeout(10)
            return bytes(records)
    raise HostAgentDenied()
