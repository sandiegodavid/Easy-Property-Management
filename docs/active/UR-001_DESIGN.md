# UR-001 — Universal Reader baseline experiment

## Status and purpose

Proposed technical design, October 23, 2026. The ten directions in [Universal Reader research](../research/universal-reader/UNIVERSAL_READER_RESEARCH.md#parallel-experimental-backlog-and-confirmed-design-decisions) were accepted October 6; the additional decisions below remain proposed. This design specifies a local XLSX reader and measurable deterministic/manual baseline, not an import implementation or production compatibility claim.

The output is source-grounded JSON arrays of candidate properties, Parties, owners, providers and relationships, with explicit uncertainty and coverage. Nothing writes official records. A candidate may be incomplete and must never be labeled import-ready merely because it passes the reader schema. No model, live database, DATA service, Google account or running server is needed.

## Scope, dependencies and delivery

UR-001 has no backlog prerequisite. It introduces its own pure contracts and standalone experimental CLI under a proposed `universal_reader` module, following the architecture's domain/application/infrastructure separation. Keep entry-point composition separate from application services. Do not register browser routes, create database tables, open a workspace or initialize domain services as a side effect of importing the reader.

| Item | Handoff |
| --- | --- |
| UR-001 | Immutable source/cell snapshots, profiles/regions, closed plans/recipes, deterministic interpretation, candidate/coverage output and benchmark harness. |
| UR-002 | Optional governed model/Jev planners propose the same plan contract. The interpreter never calls a model; planners cannot supply invented cell values. |
| UR-003 | Optional direct Sheets acquisition produces the source-neutral snapshot contract with source-specific fidelity/consistency flags. It does not call DATA-003. |
| UR-004 | FILE-001 source retention/link policy, persisted chunks/plans/candidates/answers/recipes, revision checks, audit, API review and workspace portability. |
| UR-005 | Existing-record matching and exact operator-authorized create/link/skip through Party/Portfolio/Provider domain operations. No reader output is an authorization. |
| UR-006 | Explicitly deferred experimental browser onboarding/review pilot. The standalone CLI is intentional for UR-001, not a missing UI deliverable. |

Keep all DATA scopes and dependencies unchanged. UR must not import their schemas, tables, services or routes. Existing domain contracts inform candidate fields, but importing a domain router/service is not how the standalone reader validates extraction. Future durable/source adapters call narrow application ports. Only synthetic fixtures may enter Git; consented customer samples and generated candidate artifacts remain outside the checkout.

## Current implementation assessment

| Current evidence | Design consequence |
| --- | --- |
| [Python dependencies](../../application/pyproject.toml) contain no spreadsheet parser. No Universal Reader module or import route was found in the current checkout. | Parser qualification, contracts and harness are new work. Recommend a separate optional experimental dependency set, not mandatory startup cost for all operators. |
| [Portfolio create contract](../../application/apps/server/app/modules/portfolio/api/router.py) requires structured address, type, ownership and supported inventory. | Extract these as explicit candidates; do not infer missing ownership, default to a property type, or create occupancy/lease history from spreadsheet hints. Domain validation is later. |
| [Party model](../../application/apps/server/app/modules/parties/domain/models.py) separates identity and contact methods; [Provider create contract](../../application/apps/server/app/modules/vendors/api/router.py) combines Party/profile/category inputs. | A shared Party candidate can have owner and provider projections. A provider is not a duplicate independent person; category strings are unresolved labels, not catalog IDs. |
| [AI registries](../../application/apps/server/app/modules/ai_governance/application/registry.py) have no production reader action. | No AI dependency or provider call in UR-001. UR-002 owns registration, exact disclosure, model qualification and evaluation. |
| [Workspace recovery](../modules/workspace.md) and [Files](../modules/files.md) govern canonical evidence and archives. | Standalone artifacts are not automatically managed evidence or backed up. UR-004 must register their retained form and linkage; no hidden workspace writes now. |
| [Architecture](../ARCHITECTURE.md) requires source ownership, bounded work and one writer. | Pure parsing/profiling/extraction operates outside database transactions; later integration does not add a second writer or use message Intake as spreadsheet storage. |

These observations are design-time evidence, not tests or proof of parser safety.

## How the attached research informs the design

Reviewed all eight pages and Figures 1–6 of [Spreadsheet Import Approach](../research/universal-reader/Spreadsheet_Import_Approach.pdf). It is comparative research, not implementation authority.

| PDF proposal | UR-001 disposition |
| --- | --- |
| Neutral grid → profile → discover → map → normalize, pp. 1–2 / Figure 1 | Adopt these stages, but map regions rather than one entity per sheet. Preserve raw values separately from transformations. Stop at candidate output, before review/commit. |
| Flat/grouped/tab-per-entity/cross-tab/free-text layouts, p. 3 / Figure 2 | Use as corpus archetypes, adding transposed cards, multiple regions and deliberately ambiguous examples. Support explicit spans in free text, not generated replacements. |
| Generated local scripts, pp. 3, 5 / Figures 2, 4 | Exclude. Use a versioned allowlist of bounded pure transforms. A sandbox without network does not justify arbitrary code execution. |
| Never drop unmapped data, p. 3 | Preserve and account for it as unresolved, unsupported or explicitly excluded. Do not automatically create custom fields or notes. |
| Common export adapters, concierge samples and template fallback, pp. 3–4 | Adopt as evaluation tactics after verifying actual fixture formats. No vendor-export compatibility claims or DATA template dependency. Keep original source provenance when manual preparation is measured. |
| High-confidence auto-accept, pp. 1, 5 / Figures 1, 4 | At most a proposed mapping in preview. No confidence authorizes identity grouping, exclusion or official import. Heuristic scores are not calibrated probabilities. |
| Recipes and batch undo, pp. 1–3 | Adopt declarative recipes; defer generic undo. UR-001 has no official effects to undo. |
| Spreadsheet metadata and staged entities, p. 4 / Figure 3 | Preserve epochs, merges, hidden/style cues; support XLSX only. Text preserves leading zeros when present; do not claim recoverability after numeric precision was lost. Leases/finance/history remain unsupported content. |
| Jev/provider comparison and privacy, pp. 5–7 / Figures 4–6 | Supply an identical baseline contract and held-out corpus for UR-002. No external data disclosure here. Vendor capability/retention claims require fresh qualification there. |
| 98% mappings, corrections and upload-to-commit, pp. 7–8 | Treat 98% as a hypothesis, not an approval gate. Measure omissions, exact fidelity, identity errors and manual time now; commit time/post-import errors are not measurable until UR-005/006. |

## Processing and contracts

The pipeline is **capture → structural snapshot → profile/discover → explicit plan → deterministic extract → validate/account → report**. Each stage consumes an immutable typed artifact, produces a new versioned artifact and records its semantic input digest. No stage mutates its source. Use closed JSON schemas, strict enums, finite values and explicit null/unknown states; reject unknown versions and fields. Canonical serialization and SHA-256 detect changes, not authenticity.

Proposed application ports are `capture_xlsx`, `profile_snapshot`, `discover_regions`, `validate_plan`, `extract_candidates`, `validate_coverage`, and `evaluate_run`. They receive bounded values/read-only handles and explicit settings, not ambient workspace paths or a database connection. Source acquisition is a port so UR-003 can supply a different snapshot later. Planner output passes the same validator regardless of manual, heuristic or future AI origin.

### Source and snapshot

Freeze the input into a private run directory before parsing, compute its digest while streaming, and verify the copied bytes. The parser receives only this read-only source. Modification of the original file during capture aborts rather than mixing versions. Keep the exact original XLSX beside the output for standalone evidence; a manifest explicitly states that this directory is outside EPM backup/retention. Do not upload it or print its contents to diagnostic logs.

`SourceManifest` records contract/parser version, source kind, digest/byte count, safe display filename, capture times, selected scope, resource settings and capability/fidelity flags. `WorkbookSnapshot` records workbook epoch, ordered snapshot-local sheet IDs and titles, bounded cell chunks and chunk digests, merges, hidden row/column ranges, tables/header hints, styles/fills and supported notes. Cell IDs derive from snapshot identity plus sheet ID/row/column; never use sheet titles as unique identities.

Each `CellFact` records coordinate, source type, original lexical scalar where available, decoded typed value, number format, formula text and cached result independently, merge anchor, hidden state, relevant style ID, and notes references. Preserve strings exactly, including whitespace and Unicode; transformations create separate values. Decimal scalars are strings in JSON, not binary floats. Distinguish blank, empty string, formula error and absent cached value. An XLSX source generally does not contain a reliable rendered display string for every format: store a nullable display value plus `source_provided`, `derived_supported_format` or `unavailable` fidelity. Never silently advertise a guessed rendering as exact Excel appearance.

Keep numeric lexemes and epoch metadata before parser conversion loses them. Qualify a bounded XML-level extraction path where needed alongside a high-level parser; openpyxl is a candidate from the research, not presumed sufficient for all fidelity requirements. Do not calculate formulas, open Excel/LibreOffice, fetch hyperlinks/external references, execute macros, or evaluate named-range expressions. Unsupported workbook constructs receive inventory warnings; unsupported package types fail explicitly. Formula values have unknown cache freshness; missing required caches block affected fields. Ambiguous date strings, invalid serials and unsupported display formats produce issues rather than invented values.

Inventory hidden sheets/rows/columns, initially excluded from extraction, and require explicit choices to include or acknowledge exclusion. Retain rich-text plain content and note text where qualified, while marking formatting limitations. Charts, images and drawing text are inventoried as unsupported objects, not interpreted by OCR; their omission must be visible. Metadata-only cells and objects have separate coverage so they cannot disappear or inflate business-data counts.

### Profiling and region discovery

Visit actual bounded cell records, not every position in a possibly dishonest worksheet dimension. Track sheet/region density, populated/blank counts, distinctness, bounded representative samples, observed types and lexical phone/email/date/money/ZIP/state patterns. Built-in fixed pattern detectors are permitted; plans cannot supply regex. A pattern match is evidence, not semantic truth. Deterministic sampling (up to 20 values per column) preserves selected cell references and is reproducible; extraction still examines every selected record.

Use explicit table metadata, separators, merged headings, repeated header paths and type changes to propose regions and orientations. Neither a blank row nor a subtotal-looking number alone discards data. Produce proposed rectangle bounds, header/anchor references, row/column/card orientation, grouping hints and reasons. Region discovery can abstain; cells outside proposed regions remain unresolved in coverage. Operator-authored CLI plans can split/combine regions and mark structural rows with a reason.

For overlapping regions, reuse of an owner/header cell as evidence is allowed. Conflicting record identities or two primary dispositions for a cell block the result's completeness. Merged cells resolve to their anchor without inventing values for unrelated blanks. Group carry-forward must name a reviewed start/end boundary; it stops at new headings/subtotals/section ends rather than traversing the entire sheet.

### Plans, recipes and answers

`ExtractionPlan` binds snapshot digest, schema/transform versions, authorized scope, region definitions, bounded record patterns, field mappings, explicit grouping/relationship rules, structural dispositions and operator answers. A selector is a cell, record-relative column, bounded rectangle, named group anchor or character span; spans use Unicode code-point offsets with an exclusive end. Validate every selector and bound before running it.

The initial registry includes copy, trim, bounded concatenation, explicit delimiter split, span selection, explicit locale date/number parsing, reviewed group carry-forward, repeating-block traversal and bounded unpivot. Traversal/unpivot define finite record patterns; scalar transform chains remain at most four steps. Validate output cardinality/size before expansion. No executable expressions, scripts, SQL, URLs, arbitrary regex or filesystem selectors. No freeform transform can manufacture a supported field value.

Manual interpretation remains usable without AI: the CLI accepts a documented plan and a separate answer file containing field value, rationale and source-question reference. Mark an answer `operator_entered`; it does not acquire a false cell source. Answers may resolve missing fields or grouping questions but never rewrite raw snapshot facts. Color-to-meaning needs an explicit legend answer; sheet-title values cite metadata provenance. Invalid/incomplete plans return focused issues with locations and repair guidance.

A reusable `Recipe` contains versioned selectors/patterns, transforms, structural signature and exclusion rules, without existing-domain IDs or prior authorizations. Match normalized header paths, orientation, required field types and merge topology; row-count growth is allowed only by bounded patterns. Require each selector to resolve uniquely. Changed headings/regions/types produce drift; no nearest-column fallback. Applying a recipe creates a new plan/candidate output. UR-001 stores recipes as experiment artifacts; UR-004 owns durable history and acceptance.

### Candidate arrays and identity

`CandidateBundle` binds source/snapshot, plan and answer digests, contract/transform versions and contains `parties`, `properties`, `owners`, `providers`, `ownerships`, `issues` and `coverageSummary`. Each candidate has a snapshot-local stable ID, source record-group ID, extraction status, typed fields and field provenance. IDs are deterministic for the same snapshot, plan/group identity and kind; they are not official UUIDs or stable identities across unrelated uploads. Content equality alone must not merge two records.

| Array | Initial field boundary |
| --- | --- |
| `parties` | Candidate kind (individual/organization/unknown), name and contact candidates (kind, original value, optional normalized suggestion, extension/label). Preserve ambiguous kinds/contacts for later review. |
| `properties` | Name, structured address components, proposed supported property type, notes only if mapped, inventory layout and candidate space children where present. Required gaps become issues. No inferred time zone, ownership, occupancy or availability history. |
| `owners` | Role projection referencing a Party candidate; no duplicate independent identity or claim of legal ownership. |
| `providers` | Party reference, explicitly sourced profile fields and category label candidates. Unrecognized status remains unsupported; no default preferred/avoid choice or category creation. |
| `ownerships` | Property reference and either explicit local-operator designation or client-owner Party reference; sourced share only if present, otherwise unknown. Missing/ambiguous relation blocks that relation. |

Every field stores source cell/span/metadata references or answer ID, exact raw input references, transform chain and issues. A shared source owner key may propose one Party for repeated rows only through an explicit plan grouping with consistency checks; conflicting name/contact values remain blocking. Exact email and fuzzy name similarities yield duplicate hints, never automatic identity merge. UR-001 does not query the workspace for existing records or assign real Party/category IDs. Later UR-004/005 review resolves create/link/skip.

Keep validation levels separate: extraction contract valid, reader semantic issues present/absent, and later domain eligibility. A supported address shape is not a verified Portfolio command. Do not automatically translate candidate output into domain DTOs or create inventory defaults. The exact domain operation field set and current-state validation belong to UR-005.

## Coverage and completeness

Build the ledger from actual captured facts and executed selectors, never model-reported totals. For every captured populated cell, assign exactly one primary state: `structural`, `represented`, `unresolved`, `unsupported`, or `excluded`. Extra provenance links do not increase counts. Hidden data remains represented in the inventory as excluded-pending-acknowledgment until explicitly decided. Objects/notes and formatting-only content have separate inventory/counts, with unsupported/disposition reasons.

For text spans, copying one email from a narrative cell cannot make the entire cell represented. Store covered intervals and unresolved remainder; its primary state stays unresolved until every non-structural part is accounted for or explicitly excluded. The same principle applies to partial multi-value lists. Reject overlaps that make conservation ambiguous; allow multiple evidence uses while deduplicating covered spans.

Report captured population = structural + represented + unresolved + unsupported + excluded, plus separate object metadata counts and unacknowledged exclusions. Unsupported/excluded content remains visible. Show extraction completion, accounted source and later selected-import completion as different claims. Unknown columns do not disappear into notes. A rejected/partially captured workbook cannot claim whole-source coverage; publish a failure report, not a successful partial snapshot.

## Limits, process isolation and failures

Use the research budgets and add explicit physical-artifact bounds; the added settings require agreement in the decisions below.

| Boundary | Initial contract |
| --- | --- |
| Input/package | 10 MiB compressed, 100 MiB actual expanded bytes, proposed 2,000 ZIP entries and 100:1 expansion ratio; reject duplicate/escaping/encrypted entries, unsupported compression/types and malformed package relationships. Check actual streamed expansion, not just declared sizes. |
| Grid | 20 sheets, 100 regions, 100,000 populated cells, 10,000 source groups, 200 columns per region. Count hidden/formula cells too. Proposed separate 200,000 physical cell/metadata records and 10,000 merge/style/note/object entries to bound formatted empty sheets. |
| Cell/plan | 16 KiB UTF-8 text, four scalar transforms per field; proposed 2 MiB plan and 10,000 selectors, 64 KiB per expanded candidate and 50,000 total candidate/relationship records. Reject rather than truncate. |
| Execution | One isolated preparation process per run/workspace integration, 512 MiB memory ceiling, 30 seconds per step. Parent enforces timeout, bounded output and process-tree termination; bounded worker concurrency does not depend on a job scheduler. |
| Output | Proposed 128 MiB total uncompressed artifact ceiling; chunks at most 1 MiB and pages at most 100 candidates (50 default). Stream array downloads/chunks; do not construct an unbounded single JSON object in memory. |

The parser must have no network, credentials or workspace-write authority. Removing environment variables or placing work in a subprocess is not sufficient isolation. Qualify OS-enforced resource/access restrictions on the supported Mac; if unavailable, only synthetic trusted-fixture development can proceed and customer-file readiness remains blocked. Allow necessary runtime/library reads only; input read-only and scratch/output narrowly scoped. Use safe package/XML parsing with external entities disabled; pin and qualify dependency versions. No process installation or library change occurs in this design task.

CLI commands conceptually cover inspect/snapshot, profile/discover, plan validation, extract, recipe check and evaluate. Each accepts explicit input/output and settings. Output is an immutable directory manifest, bounded snapshot/candidate chunks, plan/answers, coverage and safe report. Publish only after validation using a temporary sibling directory and atomic final rename; refuse to overwrite an existing different result. Sensitive values go only in explicitly selected private artifacts, not stdout/exception logs by default. Show aggregate counts and safe IDs on stdout; cap/sanitize parser errors.

Repeated identical inputs/settings/versions produce identical semantic digests and candidate content; timestamps/timings are excluded from those digests. A matching completed artifact may be reused after hash/schema validation. Interrupted/failed runs have no successful manifest; retry reruns pure work without official effects. Cancellation kills the worker and retains only a sanitized failure report unless the operator explicitly retains diagnostic artifacts. There is no durable job recovery or SQLite transaction in UR-001.

CLI exit categories: success, completed-with-review-issues, invalid input/plan, resource limit, canceled and internal failure; specify stable machine codes in the report. Later HTTP adapters map size/count violations to 413, malformed/unsupported input to 422, stale fingerprints to 409 and unavailable execution to 503 using shared API errors. Do not add an HTTP server just to expose these mappings now.

## Evaluation and release evidence

Begin with 30 synthetic or consented workbooks: 18 development and 12 held out, separated by source/template family. Freeze labels and corpus manifest before held-out scoring. Record source consent/provenance, layout tags, file digest and expected supported records/fields, relationships, unsupported content, deliberate ambiguities and source dispositions. Fixture variants from one template stay in one split. A corrected label or tuned recipe after held-out inspection requires a new evaluation version and disclosure; never silently reuse the score as untouched evidence.

Cover flat/stacked headers, grouped sections, transposed tables, repeated cards, one-tab-per-owner/property, cross-tabs, mixed tables, free-text spans, hidden/merged/color cues, formula caches/date epochs/precision loss, malformed packages and intentional abstention. Synthetic adversarial fixtures complement the 30-workbook usability corpus; they do not inflate its accuracy denominator. No claim of compatibility with named property-management exports without actual versioned samples.

Gold labels remain inaccessible to the discovery/extraction worker. Score initial automatic suggestions separately from operator-repaired final output. Report field exactness and supported field/record recall, wrong Party/relationship assignments, unsupported material, unreported omissions, abstention, manual corrections, mapping/review time and parser wall time/peak memory. Provide per-workbook and aggregate denominators; do not call heuristic strength a calibrated probability. The harness can record operator-measured elapsed time with participant/task metadata; if no human trial runs, report effort metrics as unmeasured, not zero. Upload-to-import and post-import errors await UR-005/006.

Acceptance requires source traceability for every emitted field, no unexplained invention or silent omission in the acceptance corpus, no wrong automatic identity merge, explicit unresolved questions, bounded hostile-input behavior and reproducible recipe drift handling. Unfamiliar layouts may abstain visibly; report their recall loss rather than excluding them from results. UR-002 later tests whether an AI planner improves the same baseline; UR-001 does not need to meet its proposed 25% time-saving hypothesis. A passing corpus does not prove universal reliability or authorize production adoption.

## Contradictions and missing decisions

The ten accepted research directions remain binding. These are the additional decisions needed to implement this particular item; recommendations below are proposed.

1. **FILE-001 source retention versus no dependencies.** Research's full pipeline starts through Files, while UR-001 is standalone. Recommend private immutable experiment input/artifact directories now; managed FILE links and portable retention only in UR-004. Clearly label artifacts outside workspace backup.
2. **UI timing has stale wording.** Backlog says defer until UI-001, which is already complete. Recommend retain the explicitly separate UR-006 browser pilot and deliver only the documented developer/concierge CLI here. Do not silently add a production onboarding page.
3. **Exact displayed/raw fidelity exceeds a simple parser conversion.** Recommend preserve numeric lexemes and explicit display-fidelity states, qualify openpyxl plus bounded structural reads as needed, and never invent Excel-rendered output. Unsupported details are visible rather than claimed exact.
4. **Candidate schema versus official domain DTOs is undefined.** Recommend the independent arrays above, nullable unresolved values, local IDs and validation levels; no existing-record lookup, real UUID assignment, domain defaults or import command generation in UR-001.
5. **Owner/provider deduplication can accidentally assert identity.** Recommend only explicit reviewed source-key grouping with conflict checks; exact email/name matches are hints. Preserve a shared Party reference without claiming it is a verified existing Party.
6. **Cell coverage hides partial narrative loss.** Recommend primary cell dispositions plus span/remainder accounting, separate metadata/object inventory and visible excluded-pending-acknowledgment. Never mark a full cell represented because one substring was selected.
7. **Manual baseline needs a usable interaction contract.** Recommend documented plan and answer files, CLI validation with focused locations/reasons, reproducible examples and measured concierge editing time. No general scripting or interactive web editor in this slice.
8. **Resource limits omit package metadata and output expansion.** Recommend the additional ZIP/member/ratio, metadata, plan, candidate and artifact ceilings above. Keep initial research budgets; expose exact settings in each result and requalify changes rather than silently increasing them.
9. **Process isolation is not yet implemented or qualified.** Recommend an optional reader dependency set and one qualified macOS isolation profile; fail customer-file readiness if access/memory/network controls cannot be enforced. Synthetic-only harness work is not hostile-file acceptance.
10. **Success criteria could mix gold/manual repair with automatic results.** Recommend frozen family-held-out labels, separate suggestion/final scores and honest unmeasured effort. Gate no silent loss/invention, but permit visible abstention with reported recall cost.
11. **Recipes and artifact replay could import authority accidentally.** Recommend content/version-bound pure artifacts without database IDs or approvals; repeat runs reproduce candidates only. Durable revision/audit/restore and official retry protocols stay in UR-004/005.
12. **PDF recommendations exceed the approved experiment.** Recommend explicitly retain its profiling/layout/corpus tactics while excluding generated scripts, automatic custom fields, confidence approval and generic undo. Its broader entity stages and vendor claims do not expand UR-001 or DATA scopes.

## Ordered implementation slices

Each slice is a coherent design handoff, not a new backlog. Resolve the additional decisions before implementation.

1. **Freeze contracts and corpus protocol.** Define closed artifact schemas, versions/digests, candidate field catalog, coverage conservation, CLI outputs and family split/label format; author small synthetic reference fixtures and expected reports.
2. **Qualify acquisition and worker isolation.** Optional parser dependencies, source freeze/digest, package preflight, actual expansion limits, process/time/memory/network/file boundaries, atomic artifact publication and safe errors. Record go/no-go for customer files.
3. **Implement faithful snapshots.** Raw/typed/formula/display fidelity, epochs, metadata/objects, sparse bounded iteration/chunks and exact source references. Test hidden and hostile metadata, not only ordinary rows.
4. **Profile and discover regions.** Reproducible pattern/sampling hints, multi-region/orientation/group discovery, proposed structure and unresolved coverage; manual plan examples for layouts the heuristic cannot resolve.
5. **Interpret plans and recipes.** Typed selectors, bounded transforms, explicit answers/grouping, drift validation, candidate arrays and exact field lineage. No model or domain writes.
6. **Complete accounting and CLI review reports.** Span-aware coverage, unsupported/exclusion handling, duplicate/relationship questions, pure retry/cancel and candidate paging/export. Demonstrate a concierge can correct a plan without changing source evidence.
7. **Run held-out baseline and hand off.** Freeze qualification settings, evaluate 12 held-out workbooks, report metrics/limitations and validate no workspace writes/network disclosure. Document UR-002/003 adapter contracts and UR-004 persistence handoff; do not declare the later pilot or import delivered.

## Validation matrix

| Area | Required evidence |
| --- | --- |
| Happy paths | Flat/grouped/card/transposed/mixed layouts; same Party referenced by owner/provider; complete source lineage; manual resolution and valid recipe reuse. |
| Invalid combinations | Unsupported package, wrong version/digest, escaped/duplicate ZIP entry, formula with missing cache, ambiguous date/type, selector outside scope, invalid span, conflicting group/overlap and unsupported color meaning. |
| Idempotency/retry | Identical semantic output on repeat; changed plan/source/settings yields distinct output; corrupt existing result refused; interrupted publication never presented as success. |
| Transaction rollback | No DB transaction or domain write exists here. Fail each artifact stage and final publish; no successful manifest or overwritten prior result. UR-004/005 separately own transaction rollback. |
| Persistence/schema | Reopen artifacts, verify all hashes/references/versions, finite typed values and primary coverage conservation; unknown transforms and tampered lineage fail. |
| Backup/restore | Standalone artifact copy/reopen verifies hashes but is not EPM backup. Assert no canonical backup scope changes; provide UR-004 retained-source/chunk contract and no automatic import on reopening. |
| Query/resource budget | Zero database/model/network calls; hostile ZIP/metadata/sparse dimensions, memory/deadline/cancel, chunk sizes, transform fan-out and output limits; no hidden unbounded scanning. |
| Fidelity and completeness | Formula/cache distinction, leading-zero/precision warnings, Unicode spans, merged anchors, hidden/object exclusions, partial narrative remainder, exact raw text preservation and no silently omitted region. |
| Evaluation | Family split isolation, gold unavailable to parser, initial versus repaired scores, deliberate abstention and denominators, manual timing honestly recorded or unmeasured. |

No application code or test execution is part of this design update.
