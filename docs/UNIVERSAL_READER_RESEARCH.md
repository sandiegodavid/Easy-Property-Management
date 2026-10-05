# Universal Reader for spreadsheet import and onboarding

October 6, 2026

## Recommendation

Build a **local spreadsheet parser plus an optional AI interpretation layer**, followed by deterministic extraction, domain validation, operator review, and import. The reader should return JSON arrays of proposed properties, owners, providers, and explicit relationships, with field-level source evidence and unresolved questions. These arrays are an intermediate candidate format, not permission to write official records.

Start with a schema-constrained LLM for unfamiliar layouts. Evaluate Jev as an alternative for bounded mapping decisions and, later, as an optional verifier. Do not require both providers for onboarding. A deterministic/manual route must work when AI is off, unavailable, or unsuitable for the customer's privacy requirements.

The central design choice is **AI proposes where and how to read; application code reads the values**. For example, a model identifies that `Portfolio!D7:D40` contains owner names; code copies those cells, preserves their coordinates, and applies approved normalization. This avoids asking a model to reproduce thousands of names, addresses, and numbers from memory. It does not eliminate incorrect mappings, which still require review.

“Universal” should mean adaptable to unfamiliar spreadsheet layouts within documented limits. No reader can reliably recover information that is absent, contradictory, encoded only in unexplained colors, or lost when a spreadsheet converted identifiers to numbers. The product should explain these limits and ask a focused question rather than claim success on every file.

This is a research and redesign proposal, not an adopted change to the backlog or existing designs. No application code, model installation, customer-data upload, or performance benchmark was performed.

## Existing contracts and implementation

The current [DATA-002 design](DATA-002_DESIGN.md) supports properties, shared Party identities for owners/providers, provider profiles/categories, and explicit property-owner relationships. It requires worksheet selection, column mapping, create/link/skip decisions, immutable source snapshots, durable outcomes, and duplicate-safe retries. It prohibits silent overwrite, merge, category creation, and fuzzy category assignment.

[DATA-003](DATA-003_DESIGN.md) changes source acquisition only: a read-only Google Sheets snapshot enters the DATA-002 pipeline. [DATA-001 in the backlog](FEATURE_BACKLOG.md) retains later lease, balance, history, and advanced update workflows. A reader may recognize these later entity types without being allowed to import them in MVP.

The [architecture](ARCHITECTURE.md) requires owning-domain rules, transaction-aware application protocols, short SQLite transactions, optional provider-neutral AI, explicit cloud disclosure, and no provider call during a database transaction. The [product brief](PRODUCT_BRIEF.md) emphasizes small portfolios, local records, and approval before AI consequences. These are suitable foundations for this proposal.

Inspection of the current server found the following implementation starting points:

- [API composition](../application/apps/server/app/bootstrap/api.py) registers the existing portfolio, Party, provider, file, and AI Governance routes, but no spreadsheet import/onboarding routes.
- [Dependencies](../application/pyproject.toml) include FastAPI, Pydantic, and SQLAlchemy, but no spreadsheet parser.
- [AI registries](../application/apps/server/app/modules/ai_governance/application/registry.py) are empty release-owned registries; there is no registered production spreadsheet action or inference adapter there.
- [AI provider ports](../application/apps/server/app/modules/ai_governance/application/ports.py) offer a common structured result boundary. Jev would need a qualified adapter converting typed decisions into the import action's payload; it is not automatically supported by the existing interface.
- [Property creation](../application/apps/server/app/modules/portfolio/application/service.py) validates ownership/inventory and resolves the property's time zone locally. [Provider creation](../application/apps/server/app/modules/vendors/application/service.py) coordinates identity, contacts, profile, and category assignments within its own transaction. These existing service entry points do not establish a resumable cross-domain import transaction protocol.

Consequently, the redesign is principally new import infrastructure, with reuse of existing domain validation and governed AI boundaries. Spreadsheet candidates should not be forced through the message/maintenance issue intake model.

## LLM versus Jev/Typesafe

### What Jev provides

TypeSafe documents three primitives: Choice selects an offered option, Score evaluates ordered rubric levels, and Noul returns a yes/no probability. Questions are evaluated independently against supplied state. There is no arbitrary text generation. This fits choosing an entity type, source column, header row, or candidate value. [TypeSafe introduction](https://docs.typesafe.ai/introduction).

Choice supports up to 255 options. The app must offer meaningful alternatives, including none/ambiguous; larger sets need partitioning. For a field mapping, choices might be `column_C`, `column_F`, `not_present`, or `ambiguous`. For a cell value, choices can be source cell/span IDs that code dereferences locally. [Choice documentation](https://docs.typesafe.ai/primitives/choice).

The official pre-parsed extraction cookbook uses code to find candidate email, phone, and amount spans, Jev to select a span, and code to copy and normalize it. This directly supports a spreadsheet selector design, but a value absent from the candidate set cannot be recovered by selection. [Pre-parsed extraction](https://docs.typesafe.ai/cookbooks/pre_parsed_value_extraction_cookbook).

TypeSafe also publishes an extraction cascade using an LLM for extraction, Jev for verification, and a stronger LLM for flagged cases. This is a useful experiment design, not evidence that the same cascade is necessary or effective for this application's workbooks. [Extraction cascade](https://docs.typesafe.ai/cookbooks/sde_cascade).

The launch article describes early access and claims large speed/cost improvements and absence of hallucination. Its schema/closed-set guarantee must not be interpreted as factual correctness. TypeSafe's own model limitations document incorrect decisions, numeric/date weaknesses, distracting context, option-order effects, and adversarial-input susceptibility. An allowed choice can still be the wrong owner, address, or column. [Launch article](https://typesafe.ai/blog/introducing-system-one-models-and-jev), [Jev limitations](https://docs.typesafe.ai/model-jaggedness/jev-1.13).

### What a general LLM adds

A general LLM can propose a compound layout plan: multiple tables, transposed records, stacked headers, repeating property cards, and fields embedded in narrative cells. Structured-output APIs can constrain the plan shape. They do not prove that its interpretation or selected cells are correct. Explicit unknown/empty outcomes and local source checks remain necessary. [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs), [Gemini structured outputs](https://ai.google.dev/gemini-api/docs/structured-output).

Local LLM inference is feasible through an evaluated runtime: Ollama documents JSON Schema output, Pydantic validation, and structured extraction. That establishes an integration mechanism, not sufficient quality on messy spreadsheets. Use the candidates in [local model research](LOCAL_MODEL_RESEARCH.md) as evaluation candidates, with no unapproved cloud fallback. [Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs).

### Comparison for this application

| Approach | Best role | Benefits | Tradeoffs |
| --- | --- | --- | --- |
| Parser + deterministic mapping | Known templates and operator-selected mappings | Offline, reproducible values, lowest operational complexity | More operator effort for unfamiliar layouts |
| Parser + hosted LLM planner | Unfamiliar layouts and compound interpretation | Flexible plan generation and text-span proposals | Disclosure, latency/cost, omissions and incorrect interpretations |
| Parser + local LLM planner | Private/offline assistance on qualified devices | Customer data can stay on-device | Hardware/setup and quality vary; constrained output does not ensure accuracy |
| Parser + Jev selectors | Header/column/entity classification and source-value selection | Closed choices and useful uncertainty signals | App must generate candidates and compose the plan; hosted dependency |
| LLM planner + Jev verifier | Later quality/cost optimization experiment | Can flag questionable mappings | Extra vendor, disclosure, calls, and failure modes; agreement is not proof |

**Recommendation:** implement the common pipeline first; qualify one LLM planner; compare Jev mapping on the same test set before adding it to production. Jev may eventually replace many LLM mapping calls for ordinary tables. It is not a standalone spreadsheet parser, and the benefit of its low latency is less compelling for occasional onboarding than for frequent real-time decisions.

## Proposed reader architecture

```text
Excel through FILE-001       Read-only Google Sheets through CONN-001
           \                         /
            Immutable local source snapshot
                         |
             Cell inventory + region discovery
                         |
       Deterministic mapping / optional AI interpretation
                         |
            Validated, bounded extraction plan
                         |
        Local plan interpreter + candidate JSON arrays
                         |
       Source accounting + domain/relationship validation
                         |
           Operator review and explicit decisions
                         |
              Confirm exact reviewed revision
                         |
       Resumable import through owning-domain operations
                         |
             Durable outcomes + provenance + audit
```

### 1. Acquire and preserve the source

Excel remains a FILE-001 source. Recommend `.xlsx` initially; arbitrary layout is separate from support for every file format. Legacy `.xls`, encrypted files, macro-enabled workbooks, PDFs, images, and CSV require explicitly qualified adapters and scope decisions. Never execute macros, formulas, external links, embedded code, or workbook instructions.

Use a bounded local parser such as openpyxl. It supports XLSX-family workbooks, but its documentation calls for protection against XML expansion attacks. Apply compressed/uncompressed size, cell-count, time, and memory limits before treating an upload as safe to inspect. [openpyxl documentation](https://openpyxl.readthedocs.io/en/stable/).

Capture a structural snapshot, not just a rectangle of strings. Include stable sheet/cell IDs, coordinates, raw typed values, displayed text/number formats, formula text and cached result, merged ranges, hidden sheet/row/column flags, relevant table/header metadata, and workbook date-system metadata. Preserve comments/notes separately if supported; never silently treat them as authoritative instructions.

openpyxl's `data_only` option returns a cached formula result rather than evaluating the formula. A missing cache must produce a visible issue; cache freshness cannot generally be proven locally. Do not recalculate by opening the customer file in Excel automatically. Read-only mode is useful for bounded memory, but reported worksheet dimensions can be wrong; parser qualification must test this. [Workbook loading](https://openpyxl.readthedocs.io/en/stable/api/openpyxl.reader.excel.html), [Optimized reading](https://openpyxl.readthedocs.io/en/stable/optimized.html).

For Sheets, retain layout metadata as well as values where needed. The API supports selected ranges/field masks; cell data distinguishes entered, effective, and formatted values. This is preferable to discarding all structure before interpretation. Read-only authorization remains required. [Spreadsheet retrieval](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets/get), [Cell data](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets/cells).

A locally frozen capture is immutable; it is not automatically a remote point-in-time snapshot across multiple fetches. Prefer one bounded fetch where feasible. If larger captures need several calls, document consistency detection/retry and show capture timing. Never substitute live Sheet values during confirmation. Batch reads and bounded backoff should respect Google's quotas. [Sheets limits](https://developers.google.com/workspace/sheets/api/limits).

### 2. Discover regions before interpreting records

Inventory all authorized sheets, then identify candidate blocks locally using populated cells, tables, blank separators, header-like rows, merged ranges, and repeated patterns. Do not initially require the operator to know which worksheet contains which entity.

The reader should propose blocks such as:

- A property directory with multiple header rows.
- An owner directory on another sheet.
- Provider cards arranged horizontally or vertically.
- A table mixing property fields and repeated owner contact details.
- Separate tables on the same sheet, with totals and repeated headers.

Blank rows and formatting are hints, not conclusive boundaries. Model interpretation may propose splitting/combining regions, but every proposed coordinate must exist within the authorized snapshot. Track uncovered content so a missed table cannot disappear behind a successful preview.

### 3. Ask AI for a constrained extraction plan

Supply a compact region description, coordinates, header candidates, representative rows, and supported target fields. Avoid uploading the whole workbook or converting it into one undifferentiated CSV/prompt.

The plan describes entity kind, region, record orientation, record boundaries, field selectors, explicit relationship keys, header/subtotal exclusions, and permitted transformations. It can select known region/column IDs or bounded source spans. It cannot specify SQL, Python, shell, URLs, arbitrary regular expressions, or executable expressions.

Use a small versioned transform registry: direct copy, trim, approved name/address component composition, bounded delimiter splitting, explicit locale-aware parsing, and narrowly scoped carry-forward from a selected merged/group anchor. Carry-forward must stop at group boundaries; a blank owner cell is not automatically the owner from the previous row.

For cells such as `Alex Rivera — owner; alex@example.test`, an LLM may propose character spans. Code checks offsets and copies the original text; it never accepts an unexplained rewritten identity. Jev can select among spans generated locally. If segmentation cannot be supported by the constrained plan, request operator correction instead of introducing an unrestricted code-generation fallback.

Use samples to understand a layout, then execute and validate against every record in that region. Rows that violate the proposed pattern become exceptions. Bound contextual model calls for those exceptions; never assume a sample establishes completeness for the rest of the workbook.

### 4. Produce candidates deterministically

The interpreter applies the validated plan to the snapshot. Preserve raw values, normalized values, field sources, transform IDs, and whether a value came from source content or an explicit operator answer.

Do not invent required information. Missing ownership designation, Party kind, property type, address components, inventory layout, or relationship effective date may require a focused question. Derive property time zones through Portfolio's existing local resolver, not a model. Do not create lease-backed occupancy or financial records from an unexplained spreadsheet label.

Preserve identifiers as strings where appropriate, including postal codes, phone numbers, and source IDs. Account for displayed leading zeros. Once Excel has destroyed significant digits, the reader must flag the uncertainty rather than reconstruct them. Money/date conversion belongs in deterministic, locale-aware code; ambiguous dates remain unresolved. DATA-001 will need stronger financial semantics than simply parsing an amount.

### 5. Validate semantics and relationships

Keep three separate results: schema validity, domain validity, and source interpretation uncertainty. Passing one does not imply the others.

Use owning-domain validators and bounded candidate lookups. Distinguish a proposed match from an authorized link. Never merge two records because their names resemble one another. Exact contact/address matches can still produce duplicate candidates needing operator choice.

Use a Party candidate identity once, with owner/provider role projections referencing it. A company appearing as both owner and provider must not automatically become two Party records. Conversely, similar names do not justify collapsing identities. The local operator's ownership is represented using Portfolio's existing ownership semantics, not a fabricated owner Party.

Provider category suggestions remain proposals. The operator decides existing category/create category/skip for each distinct source label. New category creation and provider assignment use reviewed domain operations; a model label never authorizes a catalog mutation.

### 6. Account for source coverage

Maintain an application-owned coverage ledger for populated regions/fields: represented in a candidate, unresolved, explicitly excluded, or recognized but unsupported. Preserve exclusion reasons and operator decisions. Several cells can support one field, and one source row can yield several related entities; counts must reflect these distinctions.

Show examples such as: “3 sheets inspected; 2 selected; 18 property candidates; 7 owner candidates; 12 provider candidates; 4 unresolved rows; lease and rent-history columns detected but not imported.” Hidden or unselected content must be disclosed. Never imply the entire workbook was processed if the operator authorized only selected sheets.

Reviewers must be able to inspect automatic exclusions. Unclassified populated regions prevent a claim of complete interpretation; the operator can resolve or explicitly exclude them. A model cannot establish completeness merely by reporting that it found all records.

## Candidate JSON contract

Return one versioned envelope containing arrays, references, issues, and coverage. Large results are persisted and read in bounded pages; a downloadable JSON artifact can expose the whole candidate set. Do not require one model response containing the entire portfolio.

Illustrative candidate payload, using fictional source data:

```json
{
  "schema_version": 1,
  "snapshot_id": "snapshot-01",
  "extraction_revision": 3,
  "parties": [
    {
      "candidate_id": "party-01",
      "fields": {"display_name": "Alex Rivera", "party_kind": null},
      "field_sources": {"display_name": [{"sheet_id": "sheet-01", "cell": "D7"}]}
    }
  ],
  "owners": [{"candidate_id": "owner-01", "party_candidate_id": "party-01"}],
  "properties": [
    {
      "candidate_id": "property-01",
      "fields": {"address_line_1": "123 Example Street", "property_type": null},
      "field_sources": {"address_line_1": [{"sheet_id": "sheet-01", "cell": "A7"}]}
    }
  ],
  "providers": [],
  "property_owner_relationships": [
    {
      "candidate_id": "relationship-01",
      "property_candidate_id": "property-01",
      "owner_candidate_id": "owner-01",
      "ownership_designation": null,
      "source_refs": [{"sheet_id": "sheet-01", "range": "A7:D7"}]
    }
  ],
  "issues": [
    {"candidate_id": "party-01", "field": "party_kind", "code": "confirmation_required"},
    {"candidate_id": "property-01", "code": "required_property_fields_missing"},
    {"candidate_id": "relationship-01", "code": "ownership_designation_required"}
  ],
  "coverage": {"unresolved_region_ids": [], "excluded_region_ids": []}
}
```

This intentionally incomplete example cannot be imported. Nullable extraction fields are useful for drafts; final domain commands remain strict. Candidate IDs are local references, not database IDs or executable instructions. Stable candidate identities derive from persisted source-record anchors and lineage, not display order; a changed grouping requires explicit reconciliation.

Keep operation decisions (`create`, `link`, `skip`), selected existing IDs, reviewed category decisions, and confirmation evidence separate from extraction values. Keep model-reported confidence separate from deterministic checks and operator decisions. Jev confidence is derived from the probability distribution's concentration, not a measured probability that the entire import is correct. Evaluate calibration on this dataset before setting any assistance thresholds. [Confidence documentation](https://docs.typesafe.ai/confidence).

## Operator experience

Use a shared onboarding and later-import flow, aligned with [UI-001](UI-001_DESIGN.md):

1. **Choose source.** Upload Excel or select read-only Sheets. Explain supported formats and limits.
2. **Inspect and suggest.** Preview detected entities/regions. Offer automatic interpretation only through a configured, permitted model, and retain manual mapping.
3. **Resolve questions.** Ask a few grouped questions with source previews: which address is the property address, which Party a name refers to, whether an owner is the operator or a client, and which category decision applies. Offer a scoped “apply to this region” choice rather than repeatedly asking per row.
4. **Review records.** Show proposed records and links with source drill-down, completeness/exclusions, validation issues, and create/link/skip decisions. Show likely duplicates separately. Unmapped source fields remain inspectable.
5. **Confirm import.** Name exact counts and excluded/blocked work: “Create 18 properties, 7 owners, and 12 providers; link 3 existing records; skip 4 rows.” An incomplete batch may import only explicitly selected independent eligible units. Never conceal dependencies or imply complete onboarding.
6. **Show outcomes.** Retain what succeeded, what remains blocked, and source references. Resume only unfinished units; completion reflects actual imported records.

AI interpretation, disclosure consent, mapping acceptance, and final import authorization have different meanings. Accepting a mapping populates the preview; it does not import records. A single final consequential confirmation authorizes the reviewed create/link/skip operations. Operator edits invalidate affected validation and confirmation revisions.

Onboarding is a resumable entry point into this same importer, not a second import engine. Allow skipping import and entering records manually. After import, show domain coverage gaps without implying that importing a property also supplied its leases, payment history, or maintenance obligations.

## Governance, privacy, and setup

Register bounded import interpretation actions under AI-GOV-001, with source revision/fingerprint, target schema, exact governed inputs, adapter/model provenance, limits, and redaction profiles. The import module owns plan validation and adoption.

Recommend an AI approval mode that **applies the plan to the preview**. Its atomic consequence is adopting the plan and recording the review decision, not running a multi-transaction final import. Final import authorization belongs to the importer. This avoids treating a partially committed batch as one AI approval transaction. Verify that this mode and chunk lineage fit the implemented governance contracts before coding.

Mandatory redaction cannot be bypassed because extraction needs a sensitive value. Prefer header/layout samples and consistent local surrogate IDs for identities; copy original values locally. When semantic interpretation truly needs a value that cannot be disclosed under the profile, use qualified local inference or operator mapping. Treat workbook cells as untrusted data, including prompt injection. Give models no database writes, tools, filesystem authority, or external fetch capability.

Do not retain raw spreadsheet content in generic logs. FILE-001 owns the retained source file; the importer owns the necessary normalized snapshot/candidate evidence. Define snapshot/file-link retention so cleanup cannot silently destroy evidence required by outcomes. AI Governance retains governed input under its own policies. Source/candidate exports contain customer data and require an explicit operator action.

### Jev setup and operational facts

The current model documentation lists `jev-1.13.0`, text input, a 64K total request limit and a 32K state-plus-longest-question limit. Published input pricing is $0.042 per million tokens with free output. These figures are vendor-published and may change; they do not establish application accuracy or account availability. No local weights or documented self-host deployment were established. [Models](https://docs.typesafe.ai/models).

To evaluate it: obtain account access, create an API key, use the hosted `https://api.typesafe.ai/v1/systemone` endpoint or Python `typesafe-sdk`, and pin the evaluated model version. In this application, credentials must go into the OS credential store through the adapter, not the workspace or a committed environment file. Add synthetic readiness tests, response validation, timeout/rate-limit handling, disclosure controls, and sanitized failures. [Quick start](https://docs.typesafe.ai/introduction/quickstart), [API reference](https://docs.typesafe.ai/api).

The privacy policy promises no training/fine-tuning on customer inputs but describes US hosting, service-provider processing, and purpose-based retention. No-training does not mean no-retention. The documentation offers enterprise zero retention by arrangement, which must be verified for the actual account before real data is sent. [Privacy policy](https://typesafe.ai/legal/privacy-policy), [Legal documentation](https://docs.typesafe.ai/legal).

The customer agreement allows hosted integration and warns that outputs can be erroneous; it also includes restrictions concerning competing services and distillation. Do not infer an open-model license from the SDK or plan to train a replacement model from outputs without checking terms. [Customer agreement](https://typesafe.ai/legal/mca).

Use the same provider-neutral setup for a hosted LLM. For local inference, qualify the actual runtime/model/device combination, constrain the endpoint, verify offline operation, and keep weights out of workspace backups. Switching provider or escalating to a stronger model is a new governed call; switching destination requires its own permission. Jev verification would disclose data to an additional destination and must not be enabled implicitly.

## Persistence, commit, and recovery

Extend DATA-002's batch/snapshot/decision/outcome design with source regions/cell references, extraction-plan revisions, candidate identities, field lineage, coverage decisions, and links to governed runs. Store one current greenfield schema, with versioned interpretation contracts; do not add legacy migration compatibility.

Confirmation binds the immutable snapshot digest, extraction/decision revisions, approved operation-set digest, and relevant validated domain state. Recheck identities, active categories, relationship eligibility, and required source/domain revisions at commit. A mismatch blocks the affected operation and requires refreshed review; it never silently substitutes another record.

Commit through transaction-aware owning-domain application operations composed at bootstrap. Do not insert directly into another module's SQLAlchemy tables or chain independent public create endpoints and assume that is atomic. Needed operations must accept correlation/idempotency context and the caller's transaction where coordination requires it.

Define the minimum atomic unit by domain consequence and dependency: provider identity/profile/categories; property plus required inventory and ownership links; and any newly created dependency that must not survive if its dependent operation fails. Reuse of a separately reviewed owner across several properties can use an explicit prerequisite unit. Persist the dependency graph so a failed prerequisite blocks dependents truthfully. Category decisions shared across providers likewise need a documented creation/reuse unit and retry identity.

Each atomic unit writes domain consequences, its durable result, and correlated audits in one transaction. A lost response returns the stored result for an identical retry. Changed payload under the same idempotency key conflicts. Batch partial success is deliberate and reviewable; rollback of one unit does not falsely undo previously committed independent units.

AI calls and workbook parsing occur outside write transactions. The current AI design executes synchronously and has no durable runner; do not assume a ready-made job queue. For MVP, persist bounded preparation steps/chunks and allow explicit resume, with cancellation between steps and finite timeouts. A durable background runner is a separate implementation decision if needed for acceptable responsiveness.

Re-extraction creates a new revision. Before any commit, it invalidates downstream approvals. Once some units have committed, freeze their lineage/outcomes; remaining work must reconcile against those results rather than treating a newly interpreted workbook as a fresh safe retry.

## Limits and evaluation

Proposed initial qualification ceilings: 10 MiB XLSX, 20 sheets, 100,000 populated cells, 10,000 source record groups, 200 columns per region, bounded per-cell text, and adapter-specific context/output limits below the provider maximum. These are starting recommendations, not measured production limits. Count actual expanded content; do not trust declared worksheet dimensions. Define parser memory/time and model-call/token budgets before release, and fail visibly rather than truncating silently.

Use the shared API problem contract: oversized request/import content is 413; malformed or unsupported input is 422; stale confirmation or changed idempotency payload is 409. A provider timeout is an assistance failure, not evidence that the customer spreadsheet is malformed. Preserve manual recovery.

Build a held-out, consented or synthetic workbook corpus from real layout patterns. Compare deterministic/manual mapping, LLM planner, Jev selectors, and LLM-plus-Jev verification. Separate known templates from unseen layouts; do not tune and score on the same files. Evaluate field and record recall, exact value fidelity, relationship accuracy, unreported omissions, operator correction time, abstention, latency, tokens/cost, and disclosed data volume. Model confidence alone is not an acceptance metric.

| Validation area | Required scenarios and expected evidence |
| --- | --- |
| Happy paths | Flat tables, reordered columns, stacked headers, merged groups, multiple regions/sheets, transposed cards, owner/provider role reuse, category decisions; faithful arrays and provenance |
| Invalid combinations | Unsupported entities/files, missing required fields, ambiguous dates/ownership/identity, conflicting links, archived categories, overlapping contradictory mappings; affected work blocked |
| Source fidelity/coverage | Leading zeros, formulas without caches, repeated headers/subtotals, hidden data, sparse dimensions, note fields, multirow records; omissions/exclusions visible |
| AI failures | Refusal, incomplete/schema-valid wrong plan, invalid cell/span references, prompt injection, option-order sensitivity, outage/pause, exhausted budget; no official writes and manual path retained |
| Idempotency/retry | Lost response, duplicate file/source, interrupted steps, same key with changed operation, re-extraction after partial commit; no duplicate successful consequences |
| Transaction rollback | Fail between identity/profile/category/link/outcome/audit writes; entire coordinated unit rolls back and dependents stay blocked |
| Persistence/schema | Tampered source digest, broken candidate references, invalid plan versions/lineage, inconsistent result/audit history; workspace validation fails closed |
| Backup/restore | Source evidence, snapshots, decisions, and outcomes remain explainable; credentials/weights excluded; no resumed commit without applicable revalidation |
| Query/resource budgets | Bounded page reads and batched lookups, no per-row model/database request by default, large/sparse/hostile workbooks, cancellation/timeouts; published limits enforced |

Release gates should require zero unexplained source-value invention and unreported omissions in the acceptance corpus, correct rollback/retry behavior, and meaningful reduction in operator effort against manual mapping. This is a test gate, not a guarantee of zero errors in future arbitrary files. Include deliberate abstention cases where the correct behavior is asking the operator.

## Backlog redesign and remaining decisions

Recommended scope changes for a subsequent design revision:

| Item | Proposed responsibility |
| --- | --- |
| DATA-002 | Own source snapshots, general layout interpretation, candidate arrays, lineage/coverage, manual/assisted mapping, review, domain validation, coordinated create/link/skip commits, and outcomes |
| DATA-003 | Acquire read-only Sheets values and necessary layout metadata into that same snapshot contract; retain authorization/consistency/recovery rules |
| DATA-001 | Extend the reader with separately designed lease, money, history, and update handlers; extraction does not grant permission to import these records |
| AI-GOV-001 / AI-LOCAL-001 | Provide governed inference and separately qualified local runtime support; import-specific schemas/approval consequences remain import-owned |
| FILE-001 / CONN-001 | Supply file/evidence and Sheets authorization boundaries respectively |
| UI-001 | Render the common onboarding/import workflow, source review, grouped questions, coverage, explicit confirmation, and recovery |

Contradictions and missing decisions to settle before implementation:

1. **Single-sheet/single-header mapping versus general layouts.** Replace the mandatory one-sheet workflow with selected multi-region interpretation; keep simple column mapping as its manual specialization.
2. **“No fuzzy category matching” versus AI suggestions.** Clarify that AI can offer nonbinding category candidates, while exact operator decisions authorize assignments/creation. If suggestions themselves are intended to be prohibited, disable them without weakening the reader.
3. **Arrays versus shared identity.** Adopt Party candidates plus owner/provider projections and explicit relationships, rather than independent identity-creating arrays.
4. **Snapshot detail and consistency.** Adopt cell/layout metadata, formula/hidden-content policy, and explicit multi-request Sheets consistency behavior. Values-only snapshots are insufficient for this reader.
5. **Approval meaning.** Adopt preview-only AI plan approval and a separate final import authorization bound to exact revisions; no implicit writes during extraction.
6. **AI dependencies and adapter choice.** Make assisted reading optional; require AI-GOV-001 for that path and AI-LOCAL-001 only for local inference. Qualify one planner first; Jev remains an experiment until evidence justifies it.
7. **Cross-domain atomicity.** Design domain-owned coordinated operations and dependency units before implementing commits; existing independent service methods are insufficient proof of atomic batch import.
8. **Bounds, interruption, retention, and portability.** Establish evaluated parser/model budgets, resumable-step semantics, FILE-001 link ownership, snapshot retention, and restore validators. Do not assume background jobs or automatic deletion.
9. **Unsupported data and onboarding completion.** Show recognized out-of-scope fields/entities and explicit exclusions; import success must not imply complete portfolio coverage.
10. **Later leases/balances/history.** DATA-001 needs domain-specific initial-state, effective-date, opening-balance, historical-event, and update semantics before these arrays can be committed. Recognition can precede those decisions; financial writes cannot.

The practical first experiment is a source-grounded reader for unfamiliar property/owner/provider workbooks, with a manual baseline and operator correction measurements. Adopt more providers or broader entity types only when they improve that workflow without weakening evidence, review, or domain rules.
