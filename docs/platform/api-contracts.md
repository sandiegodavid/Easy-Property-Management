# Local API contracts and recovery

## Discovery

FastAPI composition is in [bootstrap/api.py](../../application/apps/server/app/bootstrap/api.py). Each module owns router request/response models, stable error codes and application validation. The [generated contract package](../../application/packages/contracts) is the browser's typed API boundary. Use `/openapi.json` or the committed contract snapshot to inspect exact endpoint fields; do not maintain a second handwritten full API schema in module prose.

## Shared error envelope

[api_errors.py](../../application/apps/server/app/platform/api_errors.py) constructs `detail: {code, message, ...typedDetails}`. Domain routers choose their codes and statuses; clients normalize the envelope rather than parsing message prose.

| Status | Meaning |
| --- | --- |
| 413 | Request content exceeds a declared size/count/text bound |
| 422 | Malformed typed input, including other schema validation failures |
| 404 | Requested record/operation is absent |
| 409 | Revision, lifecycle, evidence, changed-key or view-continuation conflict |
| 503 | Workspace/provider/capability unavailable or busy |
| 500 | Safe internal/integrity failure when the owning boundary cannot provide a valid result |

The global request-validation handler maps declared size violations to 413 and other request-schema failures to 422. Domain-specific exceptions still use their owning router mappings; the global handler does not infer every domain failure from text.

## Commands and receipts

Use the owning revision and key on consequential mutations. A receipt returns the original committed representation; current detail supplies current state. Receipts can have separate namespaces and APIs for different aggregates. Recovery GETs never rerun a command, publish a file or fetch provider credentials.

OPS recovery registration is a separate browser integration contract. Registration alone does not enable a UI workflow. Prepare a valid canonical attempt, dispatch the owning command, then reconcile by the original key if the outcome is unknown. Preserve edits on conflict and require explicit source review before a new attempt.

## Composed reads

Counts, membership, sort and hydration share one snapshot/captured instant. Cursors bind identity/runtime, endpoint, normalized filters, source marker, time and final sort identity. View changes/expiry return a typed conflict so clients restart with retained filters. Independent section availability prevents a failed source being shown as zero or empty.

Query/page limits differ by source; read the module/router contract. Do not fetch all pages to fabricate financial/dashboard aggregates in the browser.

## Contract maintenance

From `application/`, `npm run contracts:generate` regenerates the release snapshot/types and `npm run contracts:check` verifies reproducibility. Export runs without opening the live workspace. Type checking includes generated contracts. See [frontend architecture](../ui/frontend-architecture.md) and [quality checks](../CODE_QUALITY.md).
