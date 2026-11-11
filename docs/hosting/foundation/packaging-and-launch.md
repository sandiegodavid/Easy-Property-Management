# Packaging and launch

[Foundation guides](README.md) · [Build/install commands](../deployment/packaging-and-installation.md) · [Protected launch contract](../deployment/protected-launch.md)

## Component ownership

One Python/business source distribution supports separate fixed compositions and
permissions. A request parameter cannot switch component or select a workspace.

| Artifact | Owned resources and behavior |
| --- | --- |
| Admin OCI image | Main Admin and separate Admin-recovery resources; fixed Admin entry point. Unavailable Admin-recovery resources/assets do not become a usable portal. |
| Operator OCI image | Business, hosted-access and Operator-recovery resources, compiled public SPA and fixed Operator entry point. |
| Offline host-agent bundle | Host inventory resources and restricted host-control implementation; installation alone neither starts services nor grants authority. |
| Local Operator wheel | Existing business-only resource staging and native/local transport defaults remain unchanged. |

Only the main Admin and inventory hosted baselines are implemented. Hosted-access,
Operator-recovery and Admin-recovery sets remain explicitly unavailable. Business
schema ownership stays with the existing local application. The complete six-store
and final-image proof waits for those owners; an unavailable required resource cannot
be stamped initialized or inserted as a qualified release.

## Reproducible candidate builds

Resolve dependencies inside the target Linux image, then reuse the closed lock and
binary wheels for offline builds. The initial Mac inventory did not prove Linux
marker closure; the actual Linux resolution produced 35 hash-locked wheels.
Recorded build inputs include Python 3.14.10 slim Bookworm AMD64 and setuptools 84.0.0.
The Debian container userspace and Ubuntu host kernel are separate pins, as are
Desktop-emulated AMD64 and native Linux execution. Exact hashes are in the
[packaging evidence](../qualification/reports/HOSTED_MVP_H02_4_VALIDATION.json), not
an instruction to resolve a newer moving tag.

Preparation allowlists runtime Python, declared schema resources and public assets.
Only Operator includes the compiled SPA. Final images exclude checkout/test corpora,
qualification harnesses, workspaces, seed output, environment files, source maps and
runtime compilers. Missing, modified, linked, duplicate or undeclared manifest inputs
reject. Private-key marker rejection is not a universal source-code secret detector.
Final images copy the installed environment and use UID/GID 65532; the privileged
host later selects each Operator's distinct registered runtime identity.

The agent archive has normalized sorted metadata and refuses existing output or
unexpected bundle entries. Candidate staging/install outputs never overwrite evidence.
Installed probes run outside the checkout, without network or a writable root, using
only disposable synthetic stores. Matching Admin/inventory initialization is read-only.
Missing owning stores create no destination. Agent installation needs a separate
executable temporary location; that does not relax Operator writable-tree restrictions.

Record source, dependency-lock, wheel, resource manifest, OCI platform-manifest,
config and archive hashes separately. This buildx exporter's `--iidfile` identifies
the platform manifest, not the config digest. Convenience tags are not identities.
Repeat pinned Admin/Operator wheels and full manifests reproduced byte-for-byte;
that observation is not a blanket claim of reproducibility for every image layer/tool.

## Startup and unavailable presentation

Protected root-owned bounded JSON supplies component/deployment identity, exact HTTPS
origin, generation and separate canonical mount paths. HTTP, environment workspace
values, old hosted-demo expiry configuration and local empty-workspace fallback
cannot select or repair these inputs. Launch performs validation, not initialization:

1. Validate protected binding shape, ownership, paths and current component.
2. For Operator, acquire the stable control-tree writer lock, then validate the
   existing business schema/data and workspace identity. Release the lock on failure.
3. For Admin, read-only validate its owning schema and deployment binding.
4. Keep normal hosted startup unavailable until current owning access/recovery and
   source-authority composition exists. No test-authority adapter fills that gap.

Liveness is 200; readiness and business routes stay unavailable. Bound requests
require exact Host; forwarded headers cannot replace it. The self-contained held
page is uncached, includes a bounded retry hint and exposes no internal paths, IDs,
versions, exceptions or proof details. Refresh is one GET: no polling, source read,
mutating dispatch or submission replay. Its timestamp describes availability, not
source-record freshness. Unknown hosts receive generic denial.

The status page preserves other open forms and never infers an earlier submission's
outcome. Light/dark, keyboard, 320/1280-pixel layouts and deep-link behavior have current
[focused browser evidence](qualification-and-handoff.md). This is not logged-in
Admin/operator workflow acceptance.

## Artifact and implementation references

The [native installed-candidate record](../qualification/reports/HOSTED_MVP_H02_9_VALIDATION.json)
pins the retained Admin/Operator registry digests, agent archive, dependency closure,
Caddy/cloudflared binaries and installed probes. Those artifacts were not relabelled
as final-source complete releases by later source-only tests. Final owners must
rebuild and requalify the actual installed artifacts before promotion.

Code: [candidate packager](../../../application/scripts/hosted_package.py),
[schema staging](../../../application/scripts/stage_schema_resources.py),
[installed verification](../../../application/scripts/verify_installation.py),
[schema-resource ownership](../../../application/apps/server/app/platform/schema_resources.py).
The runbooks above own exact build/probe/launch commands and safe destination rules.
