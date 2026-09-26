"""Stable FILE-001 failures and bounded metadata normalization."""
from __future__ import annotations

import re
import unicodedata

MAX_FILE_BYTES = 50 * 1024 * 1024
_MEDIA_TYPE = re.compile(r"^[a-z0-9!#$&^_.+-]+/[a-z0-9!#$&^_.+-]+(?:;[a-z0-9!#$&^_.+-]+=[a-z0-9!#$&^_.+-]+)*$")


class FileError(RuntimeError):
    """A public, stable file-store failure that never carries provider details."""

    def __init__(self, message: str, code: str = "file_request_invalid") -> None:
        super().__init__(message)
        self.code = code


class PublicationCleanupIncomplete(FileError):
    def __init__(self, publication_id: str, provider: str, original_failure: BaseException, cleanup_failure: BaseException) -> None:
        super().__init__("File publication cleanup could not be completed.", "publication_cleanup_incomplete")
        self.publication_id = publication_id
        self.provider = provider
        self.original_failure = original_failure
        self.cleanup_failure = cleanup_failure


def normalize_filename(value: str) -> str:
    if not isinstance(value, str):
        raise FileError("File name must be text.")
    name = unicodedata.normalize("NFC", value).strip()
    if not name or name in {".", ".."}:
        raise FileError("File name must be nonblank.")
    # Unicode Cc covers both the familiar ASCII controls and C1 controls
    # (for example U+0085).  They are never meaningful in a display name.
    if "/" in name or "\\" in name or any(unicodedata.category(character) == "Cc" for character in name):
        raise FileError("File name contains unsafe characters.")
    if len(name.encode("utf-8")) > 255:
        raise FileError("File name must not exceed 255 UTF-8 bytes.")
    return name


def normalize_media_type(value: str | None) -> str:
    if not isinstance(value, str):
        return "application/octet-stream"
    media_type = value.strip().lower()
    # MIME parameters are deliberately conservative: syntactically malformed
    # declarations are safe fallback metadata, never a rendering permission.
    return media_type if _MEDIA_TYPE.fullmatch(media_type) else "application/octet-stream"
