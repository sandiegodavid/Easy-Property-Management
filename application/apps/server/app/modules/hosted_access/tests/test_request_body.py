"""Replay frees disk staging before the owning handler publishes its own copies."""

import asyncio
import errno
from tempfile import SpooledTemporaryFile

import pytest

from app.modules.hosted_access.api.request_body import (
    CHUNK_BYTES,
    _storage_exhausted,
    bounded_body,
)
from app.modules.hosted_access.domain.models import HostedAccessError


def test_body_spool_closes_on_last_replay_chunk_before_handler_and_context_exit(monkeypatch):
    spools = []

    def spool(**kwargs):
        value = SpooledTemporaryFile(**kwargs)
        spools.append(value)
        return value

    monkeypatch.setattr("app.modules.hosted_access.api.request_body.SpooledTemporaryFile", spool)

    async def scenario():
        payload = b"x" * (2 * 1024 * 1024 + 17)
        calls = 0

        async def receive():
            nonlocal calls
            calls += 1
            return (
                {"type": "http.request", "body": payload, "more_body": False}
                if calls == 1
                else {"type": "http.disconnect"}
            )

        async with bounded_body(receive) as replay:
            assert not spools[0].closed
            result = bytearray()
            while True:
                message = await replay()
                assert len(message["body"]) <= CHUNK_BYTES
                result.extend(message["body"])
                if not message["more_body"]:
                    break
                assert not spools[0].closed
            assert result == payload
            # Still inside the context/application dispatch: publication can now
            # use its reserved third copy without a retained body spool.
            assert spools[0].closed
            assert await replay() == {"type": "http.disconnect"}
        assert spools[0].closed

    asyncio.run(scenario())


@pytest.mark.parametrize("code", [errno.ENOSPC, errno.EDQUOT])
def test_handler_exhaustion_is_typed_after_cleanup_even_if_free_space_has_recovered(code):
    async def scenario():
        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        with pytest.raises(HostedAccessError) as caught:
            async with bounded_body(receive) as replay:
                assert not (await replay())["more_body"]
                raise OSError(code, "private staging path must not be disclosed")
        assert caught.value.code == "hosted_storage_quota_exceeded"
        assert caught.value.status == 507
        assert "private staging" not in str(caught.value)
        assert "original operation key" in str(caught.value)

    asyncio.run(scenario())


def test_unrelated_handler_io_error_is_not_mislabeled_as_quota():
    async def scenario():
        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        with pytest.raises(PermissionError):
            async with bounded_body(receive):
                raise PermissionError(errno.EACCES, "different failure")

    asyncio.run(scenario())


def test_wrapped_storage_failure_is_classified_by_errno_without_provider_message_parsing():
    failure = RuntimeError("opaque provider failure")
    failure.__cause__ = OSError(errno.ENOSPC, "private provider path")
    assert _storage_exhausted(failure)
    cycle = RuntimeError("cycle")
    cycle.__cause__ = cycle
    assert not _storage_exhausted(cycle)
