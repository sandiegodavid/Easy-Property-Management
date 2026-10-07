# Universal Reader for spreadsheet import and onboarding

October 6, 2026

## Recommendation

Build a **local spreadsheet parser plus an optional AI interpretation layer**, followed by deterministic extraction, domain validation, operator review, and import. The reader should return JSON arrays of proposed properties, owners, providers, and explicit relationships, with field-level source evidence and unresolved questions. These arrays are an intermediate candidate format, not permission to write official records.

Start with a schema-constrained LLM for unfamiliar layouts. Evaluate Jev as an alternative for bounded mapping decisions and, later, as an optional verifier. Do not require both providers for onboarding. A deterministic/manual route must work when AI is off, unavailable, or unsuitable for the customer's privacy requirements.

The central design choice is **AI proposes where and how to read; application code reads the values**. For example, a model identifies that `Portfolio!D7:D40` contains owner names; code copies those cells, preserves their coordinates, and applies approved normalization. This avoids asking a model to reproduce thousands of names, addresses, and numbers from memory. It does not eliminate incorrect mappings, which still require review.

“Universal” should mean adaptable to unfamiliar spreadsheet layouts within documented limits. No reader can reliably recover information that is absent, contradictory, encoded only in unexplained colors, or lost when a spreadsheet converted identifiers to numbers. The product should explain these limits and ask a focused question rather than claim success on every file.

This research supports the separate UR-001–UR-006 experimental track in [FEATURE_BACKLOG.md](FEATURE_BACKLOG.md). The experiment does not change or depend on DATA-001, DATA-002, or DATA-003. Their existing designs and scopes remain the production baseline. The reader owns independent source, candidate, review, and commit contracts; comparison with existing DATA workflows is context, not a dependency. No application code, model installation, customer-data upload, or performance benchmark was performed.

## Existing contracts and implementation

The current [DATA-002 design](DATA-002_DESIGN.md) supports properties, shared Party identities for owners/providers, provider profiles/categories, and explicit property-owner relationships. It requires worksheet selection, column mapping, create/link/skip decisions, immutable source snapshots, durable outcomes, and duplicate-safe retries. It prohibits silent overwrite, merge, category creation, and fuzzy category assignment.

[DATA-003](DATA-003_DESIGN.md) changes source acquisition only: a read-only Google Sheets snapshot enters the DATA-002 pipeline. [DATA-001 in the backlog](FEATURE_BACKLOG.md) retains later lease, balance, history, and advanced update workflows. The experimental reader may recognize these entity types, but UR-005 imports only properties, owners, providers, and their reviewed relationships. Any broader experimental import needs a new item and domain design; DATA-001 does not implicitly supply that extension.

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

UR-003 independently acquires Sheets snapshots through CONN-001, without calling DATA-003 or DATA-002. Retain layout metadata as well as values where needed. The API supports selected ranges/field masks; cell data distinguishes entered, effective, and formatted values. This is preferable to discarding all structure before interpretation. Read-only authorization remains required. [Spreadsheet retrieval](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets/get), [Cell data](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets/cells).

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

Preserve identifiers as strings where appropriate, including postal codes, phone numbers, and source IDs. Account for displayed leading zeros. Once Excel has destroyed significant digits, the reader must flag the uncertainty rather than reconstruct them. Money/date conversion belongs in deterministic, locale-aware code; ambiguous dates remain unresolved. Any future experimental financial adapter needs stronger financial semantics than simply parsing an amount.

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

UR-004/005 own experimental batch/snapshot/decision/outcome contracts, source regions/cell references, extraction-plan revisions, candidate identities, field lineage, coverage decisions, and links to governed runs. Do not reuse DATA-owned tables or require DATA services. Shared infrastructure can be reused through existing application protocols without changing another backlog’s scope. Store one current greenfield schema, with versioned interpretation contracts; do not add legacy migration compatibility.

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

## Comparison with the attached spreadsheet-import research

The supplied [Spreadsheet_Import_Approach.pdf](../biz/Spreadsheet_Import_Approach.pdf), “Importing Messy Spreadsheets,” was reviewed across all eight pages, including Figures 1–6. It is a proposal to evaluate, not a source of executable instructions or authority to change backlog scope. Both reports favor local parsing, AI proposals, operator control, read-only sources, provenance, and a provider comparison. The PDF adds useful profiling and pilot tactics; this report defines stricter extraction/commit boundaries and more detailed recovery and completeness requirements.

| Topic and PDF location | Attached research | Universal Reader position and disposition |
| --- | --- | --- |
| Pipeline, pp. 1–2, Figure 1 | Neutral grid, profiling, structure detection, mapping, normalization, relationship resolution, review, commit | Agree. Add explicit bounded extraction-plan validation, field-level evidence, source coverage, version-bound authorization, and durable recovery. |
| Profiling, p. 1 | Fill rates, sample values, and phone/email/date/money/ZIP/state patterns | Adopt in UR-001. These make candidate mappings cheaper and easier to inspect. Patterns are evidence of type, not proof of a field's meaning. |
| Layouts, p. 3, Figure 2 | Flat/grouped/tab-per-entity/cross-tab/free-text archetypes | Adopt as corpus/recipe categories. A region, rather than a whole sheet, is the mapping unit; one sheet can contain several entity types. Carry-forward stops at reviewed group boundaries. Unpivoting can be a registered bounded transform without authorizing financial import. |
| Generated transform scripts, pp. 3, 5, Figures 2/4 | LLM writes scripts; run locally without network in a sandbox and save recipes | Defer unrestricted scripts. No network alone does not prevent local file access, secrets exposure, resource exhaustion, or writes. Use validated cell selectors and allowlisted transforms first. A script executor would require a separately approved capability and isolation design. |
| Unmapped data, p. 3 | Preserve everything as custom fields or notes | Preserve source evidence and unresolved fields, but do not automatically put them into official records. Custom fields require a domain schema; indiscriminate notes can duplicate sensitive or unsupported data. Offer reviewed note mapping, leave unsupported fields in staging, or record an explicit exclusion. |
| High-confidence acceptance, pp. 1, 5, Figures 1/4 | Auto-accept confident items and review exceptions | Accept only as preview preselection. Every proposed mapping stays inspectable and the exact final operation set requires operator authorization. Model confidence never authorizes a link, category creation, merge, or commit. |
| Reusable recipes, pp. 1–3 | Save mappings/scripts for re-import | Adopt declarative recipes with parser/schema/transform versions and a layout signature. Validate against every new snapshot; layout drift produces new review, not silent old mapping reuse. A recipe is neither an identity map nor standing import permission. |
| Batch undo, p. 1 | Commit with batch ID and undo | Agree on batch identity; defer generic undo. Imported records can acquire later dependencies. Compensation must use domain-owned archive/correction/reversal rules and new authorization, never delete a batch's rows blindly. Atomic rollback and idempotent retry remain required. |
| Staged entities, pp. 3–4, Figure 3 | Properties/owners/providers, then units/leases, then maintenance/history; defer balances | Initial entity set agrees. Subsequent stages are ideas, not changes to DATA items or preauthorized UR scope. Every new official entity/action needs separate domain decisions. |
| Common-source adapters and concierge pilots, pp. 3–4 | Export adapters, setup assistance, consented anonymized samples, template fallback | Adopt concierge fixture collection and a template fallback as evaluation tactics. Add source-specific recipes only after actual samples justify them; export layouts must be verified. Charging setup fees is a business decision, not a technical requirement. |
| Spreadsheet details, p. 4 | Epochs, formats, merges, hidden content, colors, legacy files, CSV | Agree on test cases. Preserve colors as cues; require an explicit legend before assigning business meaning. Format support is qualified separately from arbitrary layout support. A numeric cell may lose leading zeros/precision; text storage itself does not cause that loss. |
| Sheets, p. 4 | Read-only snapshots, selected-file/export routes, narrow authorization | Agree. UR-003 has its own capture contract and uses CONN-001 directly. XLSX exported manually can enter UR-001. A multi-fetch local snapshot must not be presented as an automatically atomic remote capture. |
| Jev fit, pp. 5–6 | Useful classifier/selector, not full ETL; possibly unnecessary at onboarding volumes | Agree. Jev remains optional. Compare it with heuristics and LLM plans before adding a production vendor or verifier. Its typed output does not prove mapping correctness. |
| Privacy, p. 6, Figure 5 | Minimize/mask; obtain consent; retention/training terms not established | Agree on controls. The existing primary-source research above supplies the missing distinction: documented no-training, purpose-based standard retention, enterprise zero retention by arrangement, and no established local model deployment. |
| Benchmark, pp. 6–8, Figure 6 | 20–30 messy sheets; correctness at fixed review burden, confidence, cost, privacy; 98% hypothesis | Adopt 20–30 workbooks as an initial pilot corpus, stratified by layouts and separated into tuning/held-out subsets. Report uncertainty and counts; that size does not establish production reliability. The 98% target is a hypothesis for mapping suggestions, not an import authorization policy. Also measure record/field omissions, wrong links, exact-value fidelity, and post-import errors. |

The greatest practical additions from the PDF are **column profiling, explicit layout archetypes, reusable declarative recipes, concierge samples, and template fallback**. The most consequential differences are **generated scripts, automatic acceptance, custom-field fallback, and undo**. They must not be bundled into a reader experiment merely because they appear in a suggested pipeline.

### Refinements adopted for the experiment

- Profile each region/column locally: bounded samples, fill rate, type-pattern rates, uniqueness, and candidate keys. Samples help planning; every source record still receives deterministic extraction and validation.
- Save declarative recipes independently of customer records. Include source layout signature, supported entity/field versions, selectors, transforms, and exclusions. Verify structural compatibility on reuse and require fresh identity/link/category/operation decisions.
- Preserve relevant cell fills/style identifiers for inspection. A reviewed legend can inform a status mapping; colors alone cannot authorize a lifecycle transition.
- Pilot with assisted imports and consented, genuinely de-identified fixtures. Keep a manual/template baseline so time savings are measured against a usable alternative. Preserve a held-out set and distinguish synthetic results from customer results.
- Treat exception-first review as a presentation strategy. Show the full proposed operation set and exclusions at final confirmation; a selected default is never an approval event.

These refinements are recorded in UR-001/004/006 and do not amend DATA designs, the main UI-001 delivery scope, or the existing production onboarding contract.

## Parallel experimental backlog and confirmed design decisions

The [experimental backlog](FEATURE_BACKLOG.md#experimental--universal-reader-parallel-track) uses a separate UR prefix. Existing DATA scopes, dependency lists, and production paths remain unchanged. Existing items do not acquire UR prerequisites.

| Item | Experimental responsibility | Boundary |
| --- | --- | --- |
| UR-001 | Corpus, XLSX snapshots, profiling, regions, constrained transforms, manual/deterministic candidates, coverage, baseline measurements | Standalone fixtures/CLI; no official writes or DATA prerequisite |
| UR-002 | Governed LLM/Jev planning and optional verification comparison | UR-001 + AI-GOV-001; provider-qualified, no import permission |
| UR-003 | Read-only Sheets source and capture consistency | UR-001 + CONN-001; own snapshot adapter, no DATA source path |
| UR-004 | Durable staging, revisions, recipes, CLI/API review, decisions, audit, portability | Own import experiment schema; foundation capabilities only; no official writes |
| UR-005 | Exact reviewed authorization, domain-owned coordinated import, durable outcomes/retry | UR-004 + existing Party/Portfolio/Provider capabilities; no DATA commit engine |
| UR-006 | Opt-in experimental onboarding/review UI and operator pilot | UR-005 + UI-001; separate experimental routes, not an amendment to UI-001 |

UR-002 and UR-003 are optional branches. UR-004/005 must support local deterministic/manual extraction without either branch. If AI or Sheets is selected, its corresponding qualified experimental capability is required. Local inference requires the separately qualified AI-LOCAL-001 configuration. No per-vendor item or provider hard dependency is needed before evaluation establishes value.

The no-DATA boundary includes implementation contracts: UR must not call DATA services or use their tables, schema definitions, routes, or required UI flows. It may reuse existing file, governance, connector, Party, Portfolio, Provider, audit, and workspace application protocols. Any eventual consolidation is a future explicit decision, not part of this experiment.

The operator approved all ten directions on October 6, 2026. The following contracts elaborate those decisions for the individual UR designs. They are proposed implementation contracts, not implemented capabilities. Numerical budgets are initial experimental qualification settings; changing them requires a documented configuration/version and renewed resource testing, not silent expansion.

### 1. Layouts and format support — UR-001

**Accepted input:** valid, unencrypted `.xlsx` packages. Validate package structure and detected content as well as the extension. Reject legacy `.xls`, `.xlsm`, `.xlsb`, encrypted packages, and unsupported containers with a specific explanation. CSV, PDF/image OCR, and additional formats are future qualifications. A manually exported Google Sheet in XLSX uses this same route; direct Sheets acquisition is UR-003.

**Representation:** assign stable snapshot-local sheet IDs, retain original titles, and address cells by sheet ID plus row/column coordinates. A region has a stable ID, rectangular bounds, proposed entity kinds, header/record orientation, and inclusion state. Multiple regions can exist on a sheet, and a region can yield a property plus related owner candidates. A source record is a persisted group of cells, not necessarily one physical row.

The first transform registry supports direct copy, trim, bounded concatenation, explicit delimiter split, extraction by validated character span, locale-specific date/number conversion, repeating-block traversal, reviewed group-anchor carry-forward, and bounded unpivot. Each transform has a version, typed parameters, input/output bounds, and a pure implementation. No generated expression, regex, Python, SQL, shell, or URL is executable. An unpivoted rent table may be recognized in staging but cannot create financial records.

Selectors include a cell, a record-relative column, a bounded range, a named group anchor, or a character span in one cell. Validate references before interpretation. Reject selectors outside the authorized source, invalid spans, contradictory field mappings, and transforms with incompatible types. A transform chain is at most four steps. Required-field failures become candidate issues rather than inferred defaults.

**Overlaps:** the same owner cell can legitimately support several relationships, and shared header/anchor cells may be reused. Two regions assigning the same record to contradictory identities are blocking conflicts. Every data cell has a primary coverage disposition; additional evidence references do not inflate coverage counts. Merged ranges retain their anchor; fill-forward applies only to an explicitly reviewed group and stops at its boundary. Blank cells elsewhere remain unknown.

**Acceptance evidence:** flat, stacked-header, grouped, transposed, repeating-card, and mixed-region fixtures; exact field copying; correct group boundaries; overlap conflicts; unknown fields; no execution of workbook content; unsupported-format errors; and bounded expansion of sparse/hostile packages.

### 2. Independent persistence — UR-004/005

Introduce a `universal_reader` domain module with UR-owned persistence and `/api/experimental/universal-reader/...` contracts. Its tables and validators do not import DATA schemas. UR-001 can use fixture files and transient CLI results before this durable module exists.

| Logical record | Required retained content |
| --- | --- |
| `ur_batches` | UUID, source kind, lifecycle state, current plan/candidate/decision revisions, actor/time, preparation status, last sanitized error |
| `ur_snapshots` | Batch reference, immutable source digest, capture metadata, FILE-001 source reference where applicable, parser/schema versions, workbook metadata, selected scope |
| `ur_snapshot_chunks` | Ordered bounded canonical JSON cell/layout chunks, chunk digest, snapshot reference; exact original cell values remain separate from normalization |
| `ur_plan_revisions` | Immutable revision, region/selector/transform plan, plan digest, parent revision, manual or governed-run provenance |
| `ur_candidate_revisions` | Candidate ID/kind/revision, typed draft fields, field sources, transform lineage, validation issues, explicit operator edits |
| `ur_recipe_versions` | Recipe ID/version, structural signature, schema/parser/transform compatibility, declarative plan, publication status |
| `ur_decision_revisions` | Reviewed create/link/skip/category/relationship/exclusion choices, candidate references, actor/reason/time; edits append a revision |
| `ur_authorizations` | Exact selected operation-set digest, bound source/revisions, validation read set, actor/time, active/consumed/revoked state |
| `ur_operations` | Frozen unit commands and dependencies, stable idempotency key, request fingerprint, correlation ID, execution state |
| `ur_outcomes` | Operation result, domain IDs or blocking/failure codes, immutable response snapshot, time, correlated audit references |
| `ur_preparation_steps` | Bounded step/chunk identity, input fingerprint, status, attempts, interruption/error result, governed-run references |

These are logical schema requirements; physical design must avoid redundant copies of large source bodies. Persist paged candidate/decision rows rather than one unbounded portfolio JSON document. Enforce uniqueness of batch revision identities, snapshot/chunk order, operation keys, and successful terminal outcomes. Canonical JSON plus SHA-256 provides integrity/change detection, not authentication.

A source FILE-001 link is owned by the UR batch/snapshot through a registered link policy. A Sheets capture retains the selected normalized grid locally; it does not retain Google credentials. Source evidence cannot be unlinked while retained plans/outcomes require it. No automatic expiry or physical deletion is introduced: explicit batch abandonment hides draft work while retaining evidence/audit under current FILE-001 behavior. Portable backups include UR rows and referenced managed files; keys and local model artifacts remain excluded.

Workspace-open/restore validators check chunk/source digests, legal revision chains, acyclic candidate/operation references, registered plan versions, coverage conservation, authorization bindings, outcome/domain references, and audit correlation. Unknown schema/transform versions fail closed. Restored unfinished commits return to a recovery check; restore does not grant fresh authorization to execute.

### 3. Shared identities and category suggestions — UR-001/004/005

Separate `PartyCandidate`, `PropertyCandidate`, `ProviderCandidate`, and `OwnershipCandidate`. Owner/provider projections reference a Party candidate; Portfolio ownership uses either `local_operator` with no Party or `client_owner` with an explicitly selected Party. Retain supported spaces only as required property inventory children; do not create lease/occupancy history from spreadsheet hints.

Each Party requires reviewed individual/organization kind and name. Contacts retain source references and use Party-owned normalization/validation. Same-source keys can propose grouping repeated owner details; conflicting names/contacts block grouping. Neither a fuzzy name match nor an exact email proves identity. Existing-record searches return bounded candidates with reasons; the operator chooses link, create a separate identity with duplicate acknowledgment, or skip.

**Link means reuse, not update.** Linking an existing Party does not overwrite its name/contacts. A new provider role/profile on a linked Party is a separately named, reviewed create consequence only if the provider domain supports it. Linking an already existing provider makes no profile/category updates. Any apparent missing data on an existing record is reported separately; arbitrary update is outside UR-005.

For each distinct source category label, retain original text and a normalized comparison key. Offer existing active category IDs, reviewed new label, or skip. AI may rank options, but no option becomes a decision without operator acceptance. Revalidate catalog state and uniqueness at commit; an archived/renamed/conflicting selection blocks the unit. Creating a category shared across providers requires explicit catalog creation authorization and a stable result reused by dependents. Provider identity/profile and selected assignments must commit together. An explicitly uncategorized provider is permitted and shown as such.

Review property type, complete supported US address, required inventory, operational ownership designation, and effective-date handling through the existing domain command contracts. Do not infer legal ownership shares. Where the domain uses the property-local current date on creation, disclose and bind that effective date during review; if review crosses that date boundary, refresh authorization rather than changing it silently.

### 4. Snapshot consistency and fidelity — UR-001/003

Retain typed raw cell value, formatted/display value, number format, formula text, cached/effective result, source date system, merge anchor, hidden flags, relevant fill/style IDs, and notes when supported. Source text is preserved exactly; normalized values get separate transform lineage. The operator can compare both in the preview.

Dates use the captured workbook epoch and a selected parsing convention. Text such as `04/05/26` remains ambiguous until the region's date convention is confirmed. Never silently treat an Excel serial as money or a phone number. Preserve text identifiers and visible leading zeros; flag values whose original precision cannot be recovered. Formula-derived required fields with no cached result are blocked. Formula caches with unknown freshness carry an explicit review acknowledgment; no automatic recalculation or external-link fetch occurs.

Hidden sheets/rows/columns are inventoried and initially excluded from extraction, with visible counts and an explicit include/exclude choice. Color is a preserved cue. Only an operator-confirmed legend can map a fill to a candidate status, and unsupported lifecycle statuses remain staging information. Sheet names may supply a field only through a visible source reference and accepted mapping.

For direct Sheets, capture selected ranges and required layout metadata through the read-only connection. **Initial pilot:** one bounded data retrieval for the selected grid, with no silent multi-call fallback. If it exceeds the capture bound, ask the operator to narrow scope or use an XLSX export. Multiple selected ranges can belong to the same bounded retrieval; describe it as captured data, not a contractual remote transactional snapshot.

Any later multi-call mode must store capture start/end, all fetched ranges, retry history, and consistency checks. A before/after revision observation or matching repeated read helps detect edits but does not prove atomicity. Such captures need a truthful consistency label and explicit operator acknowledgment, or must be rejected. Final import always reads the stored local snapshot; remote edits never replace it.

### 5. Approval meaning — UR-002/004/005/006

Use three distinct decisions:

1. **Disclosure permission:** the selected governed model may receive the stated bounded data classes. It authorizes neither mapping nor import.
2. **Apply interpretation:** a reviewed manual plan or AI draft is adopted into UR preview state. For AI, the domain-owned `apply_to_preview` handler validates source/draft versions and commits the plan plus AI review decision in one transaction. No official Party/property/provider write occurs.
3. **Authorize import:** the operator confirms the exact eligible create/link/skip operation set and named exclusions. This authorization is owned by UR-005, independent of model confidence.

Model actions such as `ur.layout.propose` and `ur.mapping.verify` are proposed registered capability names, not existing registrations. Verification can add issues or suggested corrections; it cannot adopt its own revised plan or approve a commit.

Confirmation includes batch/snapshot ID and digest, plan/candidate/decision revisions, selected atomic unit IDs, operation-set digest, and relevant validation context. The server computes digests and validates eligibility; it never trusts client-supplied counts or hashes alone. Store actor `local_operator`, UTC time, explicit scope, and disclosure/AI provenance separately. The local MVP does not gain an authentication scheme from this confirmation.

Any value, linkage, category, grouping, exclusion, or selected operation change invalidates affected validation and the current authorization. Show counts by consequence, blocked dependency counts, and unsupported content before confirmation. A bulk selection is allowed only after an inspectable preview; it is not an automatic approval event.

Authorization covers identical incomplete-unit retries until revoked or made stale by relevant state. It does not cover a new snapshot, changed payload, new unit, or arbitrary rerun. A commit cancellation revokes authority for unstarted units; resume requires fresh confirmation for those units. Already committed outcomes stay immutable.

### 6. Adapter qualification — UR-002

Compare four configurations through the same candidate/plan validation boundary: deterministic/manual baseline; schema-constrained LLM planner; Jev closed-set selector; optional LLM planner plus Jev verification. All AI paths use AI-GOV-001. No direct provider call from the parser/CLI bypasses disclosure, pause, source revision, output validation, or retained governed-input rules.

For Jev, generate bounded column/region/span choices locally and include none/ambiguous outcomes. Validate returned choice IDs and probability shape. For an LLM, require selectors and registered transforms, not regenerated rows or code. Store provider/model/adapter/prompt/schema versions; local configurations additionally identify the qualified runtime/artifact. Switching or escalating models creates a separately governed run, with no implicit cloud/vendor fallback.

Begin with 30 consented or synthetic workbooks spanning the layout archetypes and intentional abstention cases. Split by source/template family into 18 development and 12 held-out workbooks; never place altered versions of the same customer template in both sets. This is an initial evaluation size, not evidence of universal reliability. Freeze labels and evaluation settings before scoring the held-out set.

Report exact-value precision, supported field/record recall, wrong identity/relationship rates, unreported omissions, operator correction minutes, total review time, refusal/abstention, latency, token/call usage, and disclosed data. Record denominators and workbook-level results; measure calibration only for probability semantics supported by the adapter. Confidence concentration is not automatically correctness probability.

No adapter passes with unexplained invention, silent omitted supported records, unauthorized writes, or broken retry/rollback in the acceptance corpus. A planner must also reduce median operator time without increasing critical relationship errors relative to baseline; the pilot should initially target a 25% reduction as a hypothesis, report variability, and retain manual fallback. The PDF's 98% mapping-suggestion target may be measured but never grants commit authority. If results do not justify Jev or combined verification, omit them.

### 7. Domain atomicity and recovery — UR-005

Expose narrow transaction-aware application protocols for Party identity/role creation, Portfolio property/inventory/ownership creation, and Provider profile/category operations. Proposed UR coordination passes a caller-owned connection, validated command, operation key, correlation ID, and expected context. Owning modules retain business rules and audit policies. Their new coordinated operations must not start nested independent transactions or expose repositories to UR.

Prepare pure parsing/time-zone work outside the write transaction, then recheck required domain context inside one immediate transaction. Never hold that transaction during model/network/file parsing. Link operations validate references but do not mutate existing fields.

Build a dependency graph before authorization. A property and its required children/ownership links are one unit; a provider and its new identity/profile/assignments are one unit. Newly created dependencies cannot be left behind accidentally when the sole dependent fails. A shared owner/category may be a separately authorized prerequisite whose successful creation is explicitly acceptable even if some dependent properties/providers remain blocked. Otherwise combine the mutually required consequences into a single unit. No automatic splitting changes this choice after confirmation.

For each unit, commit domain consequences, durable UR result, and correlated audits together. Failure at any step rolls back the whole unit. Independent successful units remain committed and visible. Dependents of a failed/blocked prerequisite are blocked, not reported as attempted successes.

An operation key is workspace-scoped and immutable, with a canonical semantic request fingerprint. Identical retry returns the stored response; a changed request conflicts. Newly uploaded identical files still undergo identity checks; a content digest alone does not mean all proposed operations were previously approved. Domain-created IDs are stored in outcomes and replace dependency candidate references only through validated result resolution.

At restart, reconcile committing units against atomic outcomes. A committed result can never be rerun because the client lost its response. A unit with no committed result has no committed consequence under the protocol and can be revalidated/retried. Recheck current Party/category/property eligibility and the specific reviewed read set; unrelated portfolio edits should not invalidate the whole batch. Changed relevant state requires refreshed review, not silent rebasing.

Cancellation stops between atomic units; it cannot interrupt a transaction midway or undo completed units. Restored workspaces require explicit recovery review before unfinished writes resume. Archive/reversal of imported domain records is an ordinary separately authorized domain action, not generic import undo.

### 8. Recipes and layout drift — UR-001/004

A recipe is a versioned declarative plan parameterized by a new source, not a script or preapproved record set. Store target kinds/field versions, relative selectors, permitted transforms, region/header patterns, reviewed exclusion rules, and a structural signature. Store neither existing-record IDs nor standing create/link permissions in a reusable recipe.

Compute the structural signature from orientation, normalized header paths, expected blocks, merge topology, required field/type patterns, and transform compatibility. Do not rely on a workbook filename or exact customer values. Parameterize customer-specific sheet names/anchors where possible; if retained, treat them as private workspace data. Recipes are not automatically exported or shared.

On reuse, require parser/schema/transform compatibility, resolve every required selector uniquely, and validate all source records. Changed headings, moved/missing columns, new regions, conflicting groups, or incompatible type patterns create a drift issue. Harmless changes such as row count can be accepted only within the recipe's bounded record pattern; they still generate a new preview and authorization.

Do not quietly select the nearest column or sheet. Present a proposed repair with before/after mapping evidence, then append a new recipe version after operator acceptance. Retain the previous version for historical plan validation. Candidate identity is rebuilt/reconciled from the new snapshot; no prior source-to-database identity binding is silently reapplied.

Recipes for common product exports require verified fixture versions and the same drift checks. Template fallback is a supported manual preparation tactic, not a guarantee that every filled template passes domain validation.

### 9. Limits and execution — UR-001/002/003/004/005

Initial experimental bounds:

| Boundary | Initial ceiling and behavior |
| --- | --- |
| XLSX input | 10 MiB compressed; 100 MiB expanded package content; reject excessive ZIP members/expansion before parsing |
| Grid | 20 sheets, 100 regions, 100,000 populated cells, 10,000 source record groups, 200 columns per region |
| Cell/plan | 16 KiB UTF-8 per text cell; at most four transforms per field; bounded selector/span lists; no silent truncation |
| Parser | One isolated preparation process per workspace, 512 MiB memory budget and 30-second step deadline; kill timed-out process and retain a sanitized failed step |
| Sheets pilot | One selected-grid retrieval, at most 2 MiB captured grid payload, finite request timeout/retries; narrow selection/export on overflow |
| AI | At most 16K input/4K output tokens per interpretation call, additionally below registered model ceilings; at most 20 calls and 200K reserved input tokens per batch |
| Reads/lookups | Default page 50, maximum 100 candidates/outcomes; lookup batches at most 100 keys, at most 10 displayed existing matches per candidate |
| Commit | One atomic unit at a time, at most 100 planned domain records per unit; larger dependency components need explicit replanning or are blocked |

Bounds are application-owned even when providers permit more. Runtime-specific memory enforcement and subprocess termination must be qualified on supported Macs before claiming readiness. The parser receives only an already-open read-only source handle/minimal input and returns bounded data; no model credentials, network capability, workspace write authority, or executable workbook hooks. Resource isolation is required for parsing untrusted packages, not for executing generated scripts.

Use one request per bounded preparation step and persist its input fingerprint/status/result through UR-004. No durable job scheduler is assumed. Long workflows advance through explicit steps with progress and resume; UR-001's standalone harness can remain transient. On startup mark abandoned running preparation steps interrupted. Reusing a successful step requires identical input/parser/plan versions; changed input creates a new step/revision.

AI-GOV-001 controls its own run interruption and result admission. UR records the interrupted/blocked result and can request an explicit new governed attempt; a retry must not falsely claim a previous provider call never happened. Provider timeouts can incur provider usage even without a usable answer, so bound attempts conservatively. Global AI pause stops model activity but leaves manual preview/edit/import available under current domain rules.

Cancellation is observed between chunks/calls/units. Do not promise that it retracts data already sent to a provider. Oversized input returns 413; malformed/unsupported input returns 422; stale revision or changed operation fingerprint returns 409. Include machine-readable UR reason codes with actionable recovery, not raw parser/provider exceptions or local paths.

### 10. Coverage and expansion — UR-001/004/006

Define coverage over the authorized captured source, not over unseen workbook content or remote resources. Every populated data cell/record region has a primary disposition: represented, unresolved, recognized-but-unsupported, or explicitly excluded. Headers/structural anchors are distinguished from data. Hidden/unselected areas appear as disclosed scope exclusions; record their operator choice without claiming they were imported.

A coverage ledger includes source reference, disposition/reason, related candidate/field IDs, decision revision, and actor/time for exclusions. A copied field points to source cells/spans; an operator-entered field points to a reviewed answer/edit record. A model cannot assert source coverage or fabricate an operator answer. Recompute the ledger from the actual interpreter result and reviewed decisions.

The review summary separates inspected sheets/regions, supported candidates, unresolved groups, excluded/unsupported fields, and eligible/blocked/selected units. Expandable exception views retain the original source. A complete *import of selected units* is distinct from complete interpretation of the authorized source and from complete portfolio onboarding. Use these separate labels in results.

Recognized lease/rent/balance/history/maintenance content stays in staging with an explanation. Unknown columns are neither dropped nor automatically converted into official notes/custom fields. The operator can select a supported notes field with explicit scope, correct a mapping, or exclude content with a reason. Their choice never turns an unsupported domain operation into an authorized one.

UR-005 permits create/link/skip for the qualified property/owner/provider consequences only. New leases, historical occupancy, maintenance cases, financial opening balances, arbitrary existing-record updates, custom-field storage, generated scripts, and batch undo each require a new experimental backlog and owning-domain contract. No DATA backlog is an implicit prerequisite or extension mechanism.

Before any later consolidation with production import, compare functionality, evidence, identity/transaction guarantees, portability, and operator effort; obtain an explicit adoption decision. Until then, experimental routes remain opt-in and existing DATA workflows remain independently deliverable.

### Implementation handoff and validation matrix

The individual UR design documents should expand these contracts into exact Pydantic/OpenAPI schemas, domain protocol signatures, database constraints, error-code enums, and test fixtures. Name any gap in an existing owning-domain operation before enabling UR-005. This report approves the design direction; it does not claim that those operations or adapters are implemented.

| Validation area | Specific required checks |
| --- | --- |
| Happy paths | Multi-region XLSX, repeated groups/cards, recipe reuse, explicit owner/provider identity reuse, reviewed catalog decision, authorized independent units |
| Invalid combinations | Unsupported format, conflicting selectors/groups, missing address/ownership, archived category, invalid linked Party, unauthorized new role/update |
| Idempotency/retry | Lost commit response, changed payload under same key, identical source uploaded again, retry after category/state drift, interrupted AI/preparation step |
| Transaction rollback | Inject failure after each coordinated domain write and before outcome/audit; prove no partial unit, dependent blocking, and preserved independent successes |
| Persistence/schema | Corrupt chunk digest, selector outside scope, broken revision/coverage chain, unauthorized outcome, unregistered recipe transform, inconsistent domain/audit evidence |
| Backup/restore | Preserve source/plan/decision/outcome lineage; no credentials/weights; draft evidence retained; unfinished writes require recovery review |
| Query/resource budgets | Constant bounded queries per page/lookup batch, no per-row model requests by default, sparse dimensions/ZIP expansion, parser deadline/memory exit, max atomic unit |
| Operator authorization | Applying AI mapping changes preview only; bulk suggestions remain inspectable; edits revoke stale authorization; cancellation requires reconfirmation for unfinished work |

The initial implementation remains a source-grounded XLSX reader and benchmark. Durable review, direct Sheets, governed AI, official import, and the later UI pilot advance through their separate UR items after their own acceptance evidence is available.
