"""Read-only independent verification for the manual Cloudflare handoff."""

import json
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from app.modules.hosted_admin.application.contracts import AdminError

MAX_PROVIDER_BYTES = 256 * 1024


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


class CloudflareSetup:
    def __init__(self, account, token, issuer, request=None):
        self.account, self.token, self.issuer = account, token, issuer
        self.request = request or self._request

    @staticmethod
    def _request(url, headers):
        try:
            with build_opener(NoRedirect).open(
                Request(url, headers=headers), timeout=10
            ) as response:
                raw = response.read(MAX_PROVIDER_BYTES + 1)
                if len(raw) > MAX_PROVIDER_BYTES:
                    raise AdminError("admin_provider_response_too_large", 503)
                return response.status, dict(response.headers), raw
        except HTTPError as error:
            # Redirect response content is irrelevant and may contain secrets.
            error.close()
            return error.code, dict(error.headers), b""
        except OSError as error:
            raise AdminError("admin_provider_unavailable", 503) from error

    def api(self, path):
        status, _, raw = self.request(
            f"https://api.cloudflare.com/client/v4/accounts/{self.account}/access/apps{path}",
            {"Authorization": f"Bearer {self.token}", "Accept": "application/json"},
        )
        if status != 200:
            raise AdminError("admin_provider_unavailable", 503)
        value = json.loads(raw)
        if not value.get("success") or value.get("result_info", {}).get("total_pages", 1) > 1:
            raise AdminError("admin_provider_observation_incomplete", 503)
        return value["result"]

    def verify(self, hostname, email):
        apps = self.api("?" + urlencode({"domain": hostname, "per_page": 100}))
        exact = [
            item
            for item in apps
            if item.get("domain") == hostname and item.get("type") == "self_hosted"
        ]
        if not exact:
            return None
        if len(exact) != 1:
            raise AdminError("admin_provider_identity_conflict", 409)
        app = exact[0]
        import re

        if not re.fullmatch(r"[a-f0-9-]{36}", app.get("id", "")) or not re.fullmatch(
            r"[a-f0-9]{64}", app.get("aud", "")
        ):
            raise AdminError("admin_provider_identity_conflict", 409)
        policies = self.api(f"/{app['id']}/policies?per_page=100")
        if (
            len(policies) != 1
            or policies[0].get("decision") != "allow"
            or policies[0].get("include") != [{"email": {"email": email}}]
            or policies[0].get("exclude")
            or policies[0].get("require")
        ):
            raise AdminError("admin_provider_policy_conflict", 409)
        status, headers, _ = self.request(f"https://{hostname}/", {})
        location = headers.get("Location", headers.get("location", ""))
        target, issuer = urlsplit(location), urlsplit(self.issuer)
        if (
            status not in {302, 303}
            or (target.scheme, target.netloc) != (issuer.scheme, issuer.netloc)
            or not target.path.startswith("/cdn-cgi/access/login")
        ):
            raise AdminError("admin_provider_enforcement_unverified", 409)
        return {"application": app["id"], "audience": app["aud"]}
