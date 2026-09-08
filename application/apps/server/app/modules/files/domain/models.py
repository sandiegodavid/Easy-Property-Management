from __future__ import annotations

from dataclasses import dataclass
@dataclass(frozen=True)
class StoredFile:
    id: str
    original_name: str
    media_type: str
    size_bytes: int
    content_sha256: str
    storage_provider: str
    storage_state: str
    local_relative_path: str | None
    s3_bucket: str | None
    s3_object_key: str | None
    s3_version_id: str | None
    provider_etag: str | None
    verified_at: str
    created_at: str
    links: tuple[dict[str, str], ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {"id": self.id, "originalName": self.original_name, "mediaType": self.media_type,
                "sizeBytes": self.size_bytes, "contentSha256": self.content_sha256,
                "storageProvider": self.storage_provider,
                "storageState": self.storage_state,
                "createdAt": self.created_at, "links": list(self.links)}
