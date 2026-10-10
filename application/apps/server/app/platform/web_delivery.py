"""Restricted delivery of trusted, packaged UI assets, independent of workspace readiness."""

from pathlib import Path
import re
from uuid import UUID
from unicodedata import category

from starlette.responses import FileResponse, JSONResponse, RedirectResponse

PACKAGED_WEB_ROOT = Path(__file__).parent.parent / "web_build"
DETAIL_PARTS = 2
SECTION_PARTS = 3
NESTED_SECTION_PARTS = 4
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "font-src 'self'; connect-src 'self'; base-uri 'none'; object-src 'none'; "
        "frame-ancestors 'none'; form-action 'self'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}
ROOT_ROUTES = {
    "/home",
    "/properties",
    "/owners",
    "/leasing",
    "/tasks",
    "/maintenance",
    "/providers",
    "/search",
    "/money",
    "/settings",
}
SECTIONS = {
    "properties": {
        "overview",
        "units",
        "leases",
        "money",
        "maintenance",
        "conversations",
        "documents",
        "details",
    },
    "owners": {
        "overview",
        "properties",
        "money",
        "leases",
        "maintenance",
        "conversations",
        "details",
    },
    "leases": {
        "overview",
        "details",
        "participants",
        "terms",
        "renewals",
        "termination",
        "money",
        "inspections",
        "documents",
        "history",
    },
    "providers": {"overview", "details", "work-history", "documents"},
}
MONEY_VIEWS = {"rent", "expenses", "deposits", "scheduled-checks", "owner-reports"}
SETTINGS_SECTIONS = {"appearance", "navigation", "workspace", "ai"}
ISSUE_SECTIONS = {
    "overview",
    "details",
    "work-journal",
    "appointments",
    "assignments",
    "conversations",
    "documents",
    "history",
}
ASSET_TYPES = {
    ".js": "text/javascript",
    ".css": "text/css",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
}


def _uuid(value: str) -> bool:
    try:
        return str(UUID(value)) == value
    except ValueError:
        return False


def browser_route(path: str) -> bool:
    """Explicit delivery eligibility, not backend capability or domain authorization."""
    if path in ROOT_ROUTES or path == "/":
        return True
    parts = path.removeprefix("/").split("/")
    if len(parts) == DETAIL_PARTS:
        kind, identity = parts
        return (
            ((kind in SECTIONS or kind in {"tasks", "inspections"}) and _uuid(identity))
            or (kind == "money" and identity in MONEY_VIEWS)
            or (kind == "settings" and identity in SETTINGS_SECTIONS)
        )
    if len(parts) == SECTION_PARTS:
        kind, identity, section = parts
        return (
            (kind in SECTIONS and _uuid(identity) and section in SECTIONS[kind])
            or (kind == "ai" and identity == "review" and _uuid(section))
            or (kind == "maintenance" and identity == "issues" and _uuid(section))
            or (kind == "money" and identity == "deposit-settlements" and _uuid(section))
        )
    return _extended_route(parts)


def _extended_route(parts: list[str]) -> bool:
    if len(parts) != NESTED_SECTION_PARTS:
        return False
    kind, group, identity, section = parts
    return _uuid(identity) and (
        (kind == "maintenance" and group == "issues" and section in ISSUE_SECTIONS)
        or (kind == "money" and group == "owner-reports" and section == "review")
    )


def accepts_html(headers: list[tuple[bytes, bytes]]) -> bool:
    for key, value in headers:
        if key.lower() != b"accept":
            continue
        for entry in value.decode("latin1").lower().split(","):
            media, *parameters = entry.strip().split(";")
            if media != "text/html":
                continue
            try:
                quality = next(
                    (float(p.strip()[2:]) for p in parameters if p.strip().startswith("q=")), 1.0
                )
                if 0 < quality <= 1:
                    return True
            except ValueError:
                continue
    return False


def _file(root: Path, relative: str) -> Path | None:
    """Never resolve a symlink into the packaged root or traverse out of it."""
    if (
        "\\" in relative
        or any(category(c) == "Cc" for c in relative)
        or any(p in {"", ".", ".."} for p in relative.split("/"))
    ):
        return None
    if any(parent.is_symlink() for parent in (root, *root.parents)):
        return None
    candidate = root
    for part in relative.split("/"):
        candidate = candidate / part
        if candidate.is_symlink():
            return None
    return candidate if candidate.is_file() else None


class PackagedWebMiddleware:
    def __init__(self, app, *, root: Path):
        self.app = app
        self.root = root.absolute()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope["path"]
        if path.startswith("/assets/"):
            response = self._asset(path, scope["method"])
        elif browser_route(path):
            response = self._entry(path, scope)
        else:
            await self.app(scope, receive, send)
            return
        await response(scope, receive, send)

    def _entry(self, path, scope):
        if scope["method"] not in {"GET", "HEAD"}:
            return self._error(405, "web_method_not_allowed", {"Allow": "GET, HEAD"})
        if not accepts_html(scope["headers"]):
            return self._error(404, "web_route_not_found")
        entry = _file(self.root, "index.html")
        if entry is None:
            return self._error(503, "web_build_unavailable")
        if path == "/":
            return RedirectResponse("/home", status_code=307, headers=self._headers())
        return FileResponse(entry, media_type="text/html", headers=self._headers())

    def _asset(self, path, method):
        if method not in {"GET", "HEAD"}:
            return self._error(405, "web_method_not_allowed", {"Allow": "GET, HEAD"})
        media = ASSET_TYPES.get(Path(path).suffix)
        asset = _file(self.root, path.removeprefix("/")) if media else None
        if asset is None:
            return self._error(404, "web_asset_not_found")
        cache = (
            "public, max-age=31536000, immutable"
            if re.search(r"-[0-9a-f]{8,64}\.", asset.name)
            else "no-cache"
        )
        return FileResponse(asset, media_type=media, headers=self._headers(cache))

    @staticmethod
    def _headers(cache="no-store"):
        return {**SECURITY_HEADERS, "Cache-Control": cache, "Vary": "Accept"}

    def _error(self, status, code, extra=None):
        return JSONResponse(
            {"detail": {"code": code}},
            status_code=status,
            headers={**self._headers(), **(extra or {})},
        )
