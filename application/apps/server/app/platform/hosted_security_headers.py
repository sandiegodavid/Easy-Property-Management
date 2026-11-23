"""Standard HTTP security headers for Pilot 0 hosted gateway and APIs (H06.4)."""

from __future__ import annotations

HSTS_HEADER_VALUE = "max-age=31536000; includeSubDomains"
PERMISSIONS_POLICY_VALUE = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
API_CSP_VALUE = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"

API_SECURITY_HEADERS: dict[str, str] = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "Strict-Transport-Security": HSTS_HEADER_VALUE,
    "Permissions-Policy": PERMISSIONS_POLICY_VALUE,
    "Content-Security-Policy": API_CSP_VALUE,
}

API_SECURITY_HEADERS_ASGI: tuple[tuple[bytes, bytes], ...] = tuple(
    (k.lower().encode("ascii"), v.encode("ascii")) for k, v in API_SECURITY_HEADERS.items()
)

API_SECURITY_HEADER_NAMES_LOWER: frozenset[bytes] = frozenset(
    name for name, _ in API_SECURITY_HEADERS_ASGI
)

CADDY_SECURITY_RESPONSE_HEADERS: dict[str, list[str]] = {
    "Strict-Transport-Security": [HSTS_HEADER_VALUE],
    "Permissions-Policy": [PERMISSIONS_POLICY_VALUE],
    "X-Content-Type-Options": ["nosniff"],
}
