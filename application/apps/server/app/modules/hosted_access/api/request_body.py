"""Bound complete request bodies before invoking a possibly consequential handler."""

import asyncio
import errno
from contextlib import asynccontextmanager
from tempfile import SpooledTemporaryFile

from starlette.concurrency import run_in_threadpool

from app.modules.hosted_access.domain.models import HostedAccessError

MAX_BODY_BYTES = 50 * 1024 * 1024 + 64 * 1024
BODY_TIMEOUT_SECONDS = 30
CHUNK_BYTES = 64 * 1024
MAX_ERROR_CAUSES = 8


def _storage_exhausted(error):
    # Owning adapters may wrap the original OS failure. Inspect only bounded,
    # explicit causes and errno, never provider/SQL exception messages.
    for _ in range(MAX_ERROR_CAUSES):
        if isinstance(error, OSError) and error.errno in {errno.ENOSPC, errno.EDQUOT}:
            return True
        error = error.__cause__
        if error is None:
            break
    return False


@asynccontextmanager
async def bounded_body(receive, *, max_bytes=MAX_BODY_BYTES):
    # Large multipart requests roll onto the service account's private TMPDIR.
    with SpooledTemporaryFile(max_size=1024 * 1024) as staged:
        try:
            async with asyncio.timeout(BODY_TIMEOUT_SECONDS):
                total = 0
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        raise HostedAccessError(
                            "hosted_body_incomplete", "Request interrupted.", 400
                        )
                    chunk = message.get("body", b"")
                    total += len(chunk)
                    if total > min(MAX_BODY_BYTES, max_bytes):
                        raise HostedAccessError(
                            "request_payload_too_large", "Request exceeds its limit.", 413
                        )
                    await run_in_threadpool(staged.write, chunk)
                    if not message.get("more_body", False):
                        break
        except TimeoutError as error:
            raise HostedAccessError("hosted_body_timeout", "Request timed out.", 408) from error
        except Exception as error:
            if _storage_exhausted(error):
                raise HostedAccessError(
                    "hosted_storage_quota_exceeded",
                    "Upload staging has insufficient storage. Contact the administrator.",
                    507,
                ) from error
            raise
        await run_in_threadpool(staged.seek, 0)
        complete = False

        async def replay():
            nonlocal complete
            if complete:
                return await receive()
            chunk = await run_in_threadpool(staged.read, CHUNK_BYTES)
            more = staged.tell() < total
            complete = not more
            if complete:
                # Multipart parsing has consumed this copy before the owning
                # handler starts staging/publication. Retaining it through the
                # response would create a fourth simultaneous on-disk copy.
                await run_in_threadpool(staged.close)
            return {"type": "http.request", "body": chunk, "more_body": more}

        try:
            yield replay
        except Exception as error:
            if _storage_exhausted(error):
                # Owning handlers can clean up temporary files before unwinding;
                # current free space alone no longer identifies that failure.
                raise HostedAccessError(
                    "hosted_storage_quota_exceeded",
                    "Storage was exhausted. Keep the original operation key, check its result, and contact the administrator.",
                    507,
                ) from error
            raise
