# AI configuration, generation and review boundaries

## Responsibility

AI governance separates source evidence, governed/redacted input, generated or externally proposed output, operator edits, approval evidence and the official domain consequence. It owns configuration, model connections, action limits, run/draft/decision history and pause controls. The owning domain validates sources and performs any approved business mutation.

## Current capability boundary

The release-owned `ACTION_REGISTRY`, `ADAPTER_REGISTRY`, redaction profiles and source validators are currently empty in production composition. The configuration/generation/review infrastructure and synthetic test adapters are implemented; this does not enable production model inference or a registered issue approval handler. Report unavailable capabilities truthfully. Model connections, assistant grants and transports are independent concepts.

## Generation and review

A registered action defines capability, source checks, input/output rules and limits. Generation reserves its run under an atomic boundary, records actual provider/model/runtime provenance and treats provider calls as external effects. Retained output is a draft. Cloud data disclosure is explicit and versioned redaction is applied before dispatch. No implicit provider fallback or unsupported modality is accepted.

Review preserves frozen source revision/fingerprint and validates current evidence before committing. Draft edits and generic dismissal remain separate decisions. Every approval, including advisory approval, requires a registered owning handler and current-source validation; governance does not write Maintenance, Finance or Lease tables directly. Global pause and per-action caps fail closed without blocking manual workflows.

Each registered action currently declares one approval effect (`create`, `update`, or `advisory_only`). Operator-selectable approval modes, link-only issue consequences and domain-owned dismissal are extensions owned by [INGEST-002](../active/INGEST-002_DESIGN.md), not delivered capabilities. Completing this foundation does not register a production action or qualify a model/runtime.

## Configuration, credentials and uncertain effects

Settings support provider-neutral connections and allowed action limits. Keys are write-only through the API and live in the OS credential store, keyed separately from portable workspace records. Backups never contain provider credentials. Restore requires reconfiguration/authorization.

Credential updates/deletion and connection probes have their own external-operation recovery. A lost response is unknown, not proof of rollback. Recover by original operation/key and explicitly acknowledge unknown outcome where required; never automatically retry a keyring/provider call. Ordinary configuration/draft commands use owning revisions, UUID keys and immutable receipt lookup.

## API and integration

`/api/ai` exposes settings, connections/disclosure/credential/test, limits, profiles, draft detail/edit/approve/dismiss and command/external-operation reads. Registry availability gates controls. Source body and generated output stay out of global activity/search. [Intake](intake.md) retains original evidence; later issue-review and connected-assistant features supply their own domain/transport contracts.

## Browser workflow boundary

Settings provides Off/device/cloud controls, registry-derived capabilities, explicit data-class disclosure, write-only credentials, synthetic probes, limits/redaction and global pause. A Settings read does not probe the transport or claim current readiness. Generic draft review preserves governed input, qualified provider/model/runtime provenance, registered confidence, predecessor links and decision/result history; approval requires a current source, registered handler and acknowledged saved version. Editing clears confirmation. Terminal drafts cannot be edited or decided again. Status-filtered draft pages use bounded server continuations and a first-page reset. External secret effects retain original-key recovery and explicit uncertainty acknowledgment. Production model/action/approval registries remain empty. See the [workflow guide](../ui/workflows.md) and [browser validation](../ui/validation.md) for implementation and evidence entry points.

## Implementation map

- [Domain values and invariants](../../application/apps/server/app/modules/ai_governance/domain).
- [Use cases and application ports](../../application/apps/server/app/modules/ai_governance/application).
- [HTTP contracts](../../application/apps/server/app/modules/ai_governance/api).
- [Persistence and source adapters](../../application/apps/server/app/modules/ai_governance/infrastructure).

Persistence identities below are read from the current models. Column definitions, checks and indexes live in the linked models and the [current baseline](../../application/database/sqlite-migrations/versions/0001_initial_schema.py); update them together.

| Tables | Model definitions |
| --- | --- |
| `ai_settings`, `ai_model_connections`, `ai_action_limits`, `ai_command_operations`, `ai_external_operations`, `ai_runs`, `ai_drafts`, `ai_review_decisions` | [sqlalchemy_models.py](../../application/apps/server/app/modules/ai_governance/infrastructure/sqlalchemy_models.py) |

## Validation

Foundation acceptance completed October 13, 2026: **82 focused backend tests**, **4 packaged browser tests**, and the shared component/recovery checks recorded in the [completed acceptance matrix](../archive/designs/AI-GOV-001_DESIGN_COMPLETED_2026-10-13.md). Real release Settings checks exercise empty registries; browser adapter/review contracts are synthetic. Backend synthetic adapters prove domain approval, redaction, concurrency, audit validation and encrypted portability without enabling production inference.

- [test_api_contracts.py](../../application/apps/server/app/modules/ai_governance/tests/test_api_contracts.py).
- [test_command_readiness.py](../../application/apps/server/app/modules/ai_governance/tests/test_command_readiness.py).
- [test_external_effects.py](../../application/apps/server/app/modules/ai_governance/tests/test_external_effects.py).
- [test_governance.py](../../application/apps/server/app/modules/ai_governance/tests/test_governance.py).
- [test_openapi_readiness.py](../../application/apps/server/app/modules/ai_governance/tests/test_openapi_readiness.py).

Use the [shared validation matrix](../platform/persistence.md#validation-matrix) when changing this boundary. Later production actions, runtimes and domain terminal-mode extensions remain in [active work](../active/README.md).
