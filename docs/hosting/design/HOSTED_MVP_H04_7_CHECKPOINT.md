# H04.7 Admin-lite UI

H04.7 implements the Admin-lite operator management interface inside the
existing Admin origin bundle (`application/apps/web/src/admin/`) per
[HOSTED_MVP_H04_DESIGN.md](HOSTED_MVP_H04_DESIGN.md).

- **Typed Admin-lite API client** (`apps/web/src/admin/admin-api.ts`):
  `adminFetch<T>()` with `credentials: "same-origin"`, `X-CSRF-Token` on `POST`
  mutations, structured `AdminApiError` (preserving `limitingResources`), and
  zero browser-storage secrets.
- **Admin-lite workspace** (`apps/web/src/admin/AdminWorkspace.tsx`):
  - **Operator Directory**: search, `setup_state` filter, `access_state` filter,
    bounded pagination (`nextCursor`), set-based status/usage/protection display
    (honestly showing `Unavailable` when unobserved or pending H05), and
    **Add operator** / **Refresh list** actions.
  - **Add Operator**: pinned **Free pilot (50.00 MB)** summary, live host
    capacity summary, qualified Operator release selector, `Empty workspace`
    (default) vs `Synthetic sample portfolio` (with pinned `seed_bundle` input),
    stable per-draft `idempotencyKey`, and full draft preservation on validation
    or `409 capacity_insufficient` errors without auto-replay.
  - **Operator Detail**: independent cards for Assignment & access, 5-gate
    Readiness (`isolation`, `schema`, `routing`, `protection`, `binding`),
    Free pilot usage + explicit **Refresh source**, latest `operation_id` for
    manual provisioning/retry, and gated **Issue / reissue invitation** with
    one-time claim link display and explicit **Mark delivered** confirmation
    (D4).
- **Shell & responsive styling** (`apps/web/src/admin/main.tsx`,
  `apps/web/src/admin/style.css`):
  Mounts `<AdminWorkspace session={session} />` once signed in, preserving all
  H03 sign-in/TOTP/sign-out flows and dark/light accessible styling across
  narrow (`390px`) and desktop (`1440px`) viewports.

## Local validation

- **Frontend checks**: `npm run lint` (0 warnings, 0 errors), `npm run
  typecheck` (205 source files passed), `npx prettier --check` on all 5 changed
  files (passed), and `npm run build:admin` (production bundle built cleanly).
- **Playwright component tests**: 8 passed in 2.9s across
  `admin-identity.spec.ts` (7 tests) and `admin-lite.spec.ts` (1 end-to-end
  workflow test covering `390px` & `1440px` viewports, `409` capacity error
  input preservation, retry success, 5-gate readiness, source refresh, and
  one-time invitation issuance + delivery confirmation).

H04.8 will implement the Operator hosted Settings panel (Free pilot usage,
honest unavailable H05 protection, support contact, no paid upgrades) and `507`
storage-limit UX while preserving local mode.
