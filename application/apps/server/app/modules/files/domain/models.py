from __future__ import annotations

from dataclasses import dataclass
@dataclass(frozen=True)
class StoredFile:
    id: str
    original_name: str
    media_type: str
    size_bytes: int
    content_sha256: str
    relative_path: str
    created_at: str
    links: tuple[dict[str, str], ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {"id": self.id, "originalName": self.original_name, "mediaType": self.media_type,
                "sizeBytes": self.size_bytes, "contentSha256": self.content_sha256,
                "relativePath": self.relative_path, "createdAt": self.created_at, "links": list(self.links)}
