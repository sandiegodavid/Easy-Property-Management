"""Build an auth-only candidate from protected inventory and resolved endpoint evidence."""

from dataclasses import dataclass
from ipaddress import ip_address, ip_network
import json
import re

from app.modules.host_agent.application.auth_routes import (
    AuthRouteManifest,
    AuthRouteObservation,
    SharedIdentityManifest,
    WORKSPACE_FORBIDDEN_PREFIXES,
    WorkspaceRouteManifest,
    WorkspaceRouteObservation,
)
from app.modules.host_agent.application.dispatch import HostAgentDenied, HostAgentUnavailable
from app.modules.host_agent.infrastructure.gateway import closed_config
from app.modules.host_agent.infrastructure.endpoint_policy import hostname
from app.platform.hosted_contracts.semantic import semantic_hash
from app.platform.hosted_security_headers import CADDY_SECURITY_RESPONSE_HEADERS


PRIVATE_BRIDGE_RANGES = tuple(
    ip_network(value) for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fd00::/8")
)


@dataclass(frozen=True)
class VerifiedAuthEndpoint:
    """Resolved by the host owner after inspecting the running artifact and network."""

    manifest: AuthRouteManifest | SharedIdentityManifest | WorkspaceRouteManifest
    address: str
    port: int
    tls_name: str
    admin_assets: tuple[str, ...] = ()
    central_assets: tuple[str, ...] = ()
    trust_der_base64: str | None = None

    def __post_init__(self):
        try:
            address = ip_address(self.address)
        except ValueError:
            raise HostAgentDenied() from None
        hostname(self.tls_name)
        if (
            len(self.admin_assets) + len(self.central_assets) > 64
            or any(
                not re.fullmatch(r"/assets/[A-Za-z0-9_-]{1,100}\.(?:js|css)", path)
                for path in (*self.admin_assets, *self.central_assets)
            )
            or (
                (self.admin_assets or self.central_assets)
                and not isinstance(self.manifest, SharedIdentityManifest)
            )
        ):
            raise HostAgentDenied()
        # The resolver owns peer/bridge identity. This layer only accepts numeric
        # private addresses and never turns a browser field into a network target.
        if (
            not any(address in block for block in PRIVATE_BRIDGE_RANGES)
            or "%" in self.address
            or type(self.port) is not int
            or not 1 <= self.port <= 65535
        ):
            raise HostAgentDenied()

    @property
    def dial(self):
        host = f"[{self.address}]" if ":" in self.address else self.address
        return f"{host}:{self.port}"


CANONICAL_UUID_PATTERN = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
UUID_PLACEHOLDERS = ("{operator_id}", "{invitation_id}", "{operation_id}")


def _uri_pattern(path: str) -> str:
    escaped = re.escape(path)
    for placeholder in UUID_PLACEHOLDERS:
        escaped = escaped.replace(re.escape(placeholder), CANONICAL_UUID_PATTERN)
    return "^" + escaped + r"(?:[?].*)?$"


def _route(origin, method, path, endpoint):
    host = origin.removeprefix("https://")
    # Use the original URI for the path check. Caddy's path matcher can decode
    # escapes and normalize a path before matching.
    uri_pattern = _uri_pattern(path)
    expression = (
        "{http.request.hostport} == "
        + json.dumps(host)
        + " && {http.request.orig_uri}.matches("
        + json.dumps(uri_pattern)
        + ') && {http.request.header.X-Forwarded-Proto} == "https"'
        + ' && {http.request.header.Cf-Connecting-Ip}.matches("^[0-9A-Fa-f:.]+$")'
        + " && {http.request.header.X-Forwarded-For} == {http.request.header.Cf-Connecting-Ip}"
    )
    upstream_headers = {"Host": [host], "X-Forwarded-Proto": ["https"]}
    delete_headers = [
        "Forwarded",
        "X-Forwarded-Host",
        "X-Forwarded-For",
        "Cf-Connecting-Ip",
    ]
    if path == "/auth/email-link" and method == "POST":
        upstream_headers["X-Epm-Client-Network"] = ["{http.request.header.Cf-Connecting-Ip}"]
    else:
        delete_headers.append("X-Epm-Client-Network")
    tls = {"server_name": endpoint.tls_name}
    if endpoint.trust_der_base64 is not None:
        tls["root_ca_pool"] = [endpoint.trust_der_base64]
    return {
        "match": [
            {
                "host": [host],
                "method": [method],
                "expression": expression,
                "header": {"X-Forwarded-Proto": ["https"]},
                "not": [
                    {"header": {name: ["*"]}}
                    for name in (
                        "Forwarded",
                        "X-Forwarded-Host",
                        "X-Forwarded-Port",
                        "X-Original-URL",
                        "X-Rewrite-URL",
                    )
                ],
            }
        ],
        "handle": [
            {
                "handler": "reverse_proxy",
                "upstreams": [{"dial": endpoint.dial}],
                "transport": {
                    "protocol": "http",
                    "dial_timeout": "5s",
                    "response_header_timeout": "5s",
                    "tls": tls,
                },
                "headers": {
                    "request": {
                        "set": upstream_headers,
                        "delete": delete_headers,
                    },
                    "response": {
                        "set": CADDY_SECURITY_RESPONSE_HEADERS,
                    },
                },
            }
        ],
        "terminal": True,
    }


def _workspace_eligible_routes(origin, endpoint):
    host = origin.removeprefix("https://")
    forbidden_alt = "|".join(
        re.escape(prefix.lstrip("/")) for prefix in WORKSPACE_FORBIDDEN_PREFIXES
    )
    forbidden_pattern = f"(?i)^/(?:{forbidden_alt})(?:/|[?]|$)"
    traversal_pattern = r"(?i)(?:^|/)\.{1,2}(?:/|[?]|$)|//|%(?:2e|2f|5c)"
    normalized_forbidden_paths = [
        item for prefix in WORKSPACE_FORBIDDEN_PREFIXES for item in (prefix, f"{prefix}/*")
    ]
    deny_route = {
        "match": [
            {"host": [host], "header": {"Upgrade": ["*"]}},
            {"host": [host], "path": normalized_forbidden_paths},
            {
                "host": [host],
                "expression": "{http.request.orig_uri}.matches("
                + json.dumps(forbidden_pattern)
                + ")",
            },
            {
                "host": [host],
                "expression": "{http.request.orig_uri}.matches("
                + json.dumps(traversal_pattern)
                + ")",
            },
        ],
        "handle": [
            {
                "handler": "static_response",
                "status_code": 403,
                "headers": {"Cache-Control": ["no-store"], **CADDY_SECURITY_RESPONSE_HEADERS},
                "body": "Request denied.",
            }
        ],
        "terminal": True,
    }
    expression = (
        "{http.request.hostport} == "
        + json.dumps(host)
        + ' && {http.request.header.X-Forwarded-Proto} == "https"'
        + ' && {http.request.header.Cf-Connecting-Ip}.matches("^[0-9A-Fa-f:.]+$")'
        + " && {http.request.header.X-Forwarded-For} == {http.request.header.Cf-Connecting-Ip}"
    )
    tls = {"server_name": endpoint.tls_name}
    if endpoint.trust_der_base64 is not None:
        tls["root_ca_pool"] = [endpoint.trust_der_base64]
    proxy_route = {
        "match": [
            {
                "host": [host],
                "method": list(endpoint.manifest.allowed_methods),
                "expression": expression,
                "header": {"X-Forwarded-Proto": ["https"]},
                "not": [
                    {"header": {name: ["*"]}}
                    for name in (
                        "Forwarded",
                        "X-Forwarded-Host",
                        "X-Forwarded-Port",
                        "X-Original-URL",
                        "X-Rewrite-URL",
                        "Upgrade",
                    )
                ],
            }
        ],
        "handle": [
            {
                "handler": "reverse_proxy",
                "upstreams": [{"dial": endpoint.dial}],
                "transport": {
                    "protocol": "http",
                    "dial_timeout": "5s",
                    "response_header_timeout": "5s",
                    "tls": tls,
                },
                "headers": {
                    "request": {
                        "set": {"Host": [host], "X-Forwarded-Proto": ["https"]},
                        "delete": [
                            "Forwarded",
                            "X-Forwarded-Host",
                            "X-Forwarded-For",
                            "Cf-Connecting-Ip",
                            "X-Epm-Client-Network",
                            "Upgrade",
                        ],
                    },
                    "response": {
                        "set": CADDY_SECURITY_RESPONSE_HEADERS,
                    },
                },
            }
        ],
        "terminal": True,
    }
    return [deny_route, proxy_route]


def auth_config(projection, settings, *, held=(), eligible=(), shared=None, login_origin=None):
    """Generate a candidate. Callers qualify and inspect it before publication."""
    records = {row.binding_id: row for row in projection.records}
    eligible_ids = {row.binding_id for row in projection.records if row.desired_state == "eligible"}
    non_eligible_records = tuple(
        row for row in projection.records if row.desired_state != "eligible"
    )
    routes = []
    seen = set()
    seen_eligible = set()
    for observation, endpoint in eligible:
        if not isinstance(observation, WorkspaceRouteObservation):
            raise HostAgentDenied()
        row = records.get(observation.binding_id)
        manifest = endpoint.manifest
        if (
            row is None
            or row.binding_id in seen
            or row.desired_state != "eligible"
            or observation.desired_state != "eligible"
            or observation.workspace_route_state != "ready"
            or observation.access_epoch != row.access_epoch
            or observation.resource_generation != row.resource_generation
            or not isinstance(manifest, WorkspaceRouteManifest)
            or observation.workspace_manifest_sha256 != semantic_hash(manifest)
            or observation.resource_readiness_proof_ref != manifest.recovery_proof_ref
            or not observation.source_identity_proof_ref
            or not observation.resource_readiness_proof_ref
        ):
            raise HostAgentDenied()
        seen.add(row.binding_id)
        seen_eligible.add(row.binding_id)
        routes.extend(_workspace_eligible_routes(row.public_origin, endpoint))
    if not eligible_ids.issubset(seen_eligible):
        raise HostAgentUnavailable()

    closed_projection = (
        projection.model_copy(update={"records": non_eligible_records})
        if hasattr(projection, "model_copy")
        else type(projection)(records=non_eligible_records)
    )
    config = closed_config(closed_projection, settings)

    for observation, endpoint in held:
        if not isinstance(observation, AuthRouteObservation):
            raise HostAgentDenied()
        row = records.get(observation.binding_id)
        manifest = endpoint.manifest
        if (
            row is None
            or row.binding_id in seen
            or row.desired_state != "held"
            or observation.desired_state != "held"
            or observation.auth_route_state != "ready"
            or observation.access_epoch != row.access_epoch
            or observation.resource_generation != row.resource_generation
            or not isinstance(manifest, AuthRouteManifest)
            or observation.auth_manifest_sha256 != semantic_hash(manifest)
        ):
            raise HostAgentDenied()
        seen.add(row.binding_id)
        routes.extend(
            _route(row.public_origin, method, path, endpoint) for method, path in manifest.routes
        )
    if shared is not None:
        manifest = shared.manifest
        if (
            not isinstance(manifest, SharedIdentityManifest)
            or manifest.central_origin != login_origin
            or {manifest.central_origin, manifest.admin_origin}.intersection(
                row.public_origin for row in projection.records
            )
        ):
            raise HostAgentDenied()
        for origin, allowed in (
            (
                manifest.central_origin,
                (*manifest.central_routes, *(("GET", path) for path in shared.central_assets)),
            ),
            (
                manifest.admin_origin,
                (
                    *manifest.admin_routes,
                    ("GET", "/"),
                    *(("GET", path) for path in shared.admin_assets),
                ),
            ),
        ):
            routes.extend(_route(origin, method, path, shared) for method, path in allowed)
    config["apps"]["http"]["servers"]["gateway"]["routes"][:0] = routes
    return config
