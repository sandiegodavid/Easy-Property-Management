# Local transport, secrets and disclosure

## Access model

The current product is a local single-operator application with no app login or tenant ACL. Bind HTTP only to loopback. This does not make browser-origin protection optional: a foreign website must not be able to drive local writes or read sensitive workspace content.

[Browser transport middleware](../../application/apps/server/app/platform/browser_transport.py) validates loopback Host and exact Origin before routes. Production uses same-origin browser requests; explicit loopback development origins are an opt-in host configuration. Null/foreign origins fail closed. Forwarded headers are not trusted.

CLI HTTP writes without Origin require `X-EPM-Local-Client: 1` and no browser Fetch Metadata/Referer. The marker is intent, not authentication, and never overrides a bad Origin. Browser requests use relative API paths and never add it.

Opening a registered public SPA page from an external link is allowed for GET/HEAD requests accepting HTML without an Origin header. When supplied, Fetch Metadata must identify document navigation. This exception serves the public entry page only: API reads, writes, cross-site fetches, frames and explicit foreign Origins retain their rejection rules.

## Files and packaged content

File paths/URLs are not public capabilities. Downloads verify recorded content, use safe attachment disposition and nosniff, and enforce owning links. Secrets, workspace files, environment files and source maps cannot enter the packaged public build. SPA fallback serves only registered supported HTML routes; unknown API paths/assets/follow-up routes cannot receive the app entry page.

## Secrets and AI

OS credential stores or the provider's host credential chain own secrets. Workspace tables, recovery, logs, audit and portable archives must not contain keys, grants, passphrases, raw account identifiers or unrestricted file locators. Credentials and assistant authorization are independent.

AI calls require explicit capabilities, redacted governed inputs and destination disclosure; pause gates optional AI while manual workflows remain usable. Production registries are currently empty. No assistant bridge or MCP endpoint is implied by an AI connection record.

## Sensitive history and reads

[Audit](../modules/audit.md) applies distinct contextual/global disclosure policies. [Intake](../modules/intake.md) commits a fail-closed sensitive-read event before returning evidence; caller-owned source adapters expose only safe facts. Metadata search does not index raw source text, documents or recovered form payloads.

## Code and validation

- [Transport tests](../../application/apps/server/app/platform/tests/test_browser_transport.py).
- [Web delivery tests](../../application/apps/server/app/platform/tests/test_web_delivery.py).
- [Web packaging tests](../../application/apps/server/app/platform/tests/test_web_packaging.py).
- [File tests](../../application/apps/server/app/modules/files/tests).
- [Intake tests](../../application/apps/server/app/modules/intake/tests).

These are executable validation entry points; consult active UI acceptance for outstanding real-browser security/recovery proof.
