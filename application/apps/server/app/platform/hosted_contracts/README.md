# Shared hosted contracts

H01.3 supplies strict values and pure envelopes for H02–H05 owners. Nothing here
opens a store, authorizes a request, sends a command or registers an API/CLI.
Owning action payloads, actor checks, transactions and persistence remain in their
application modules. The package imports only the standard library and Pydantic.
Existing business receipt/domain contracts are unchanged; the older UUID validator
cannot be imported here because its module also imports SQLAlchemy.

## Canonical semantic intent

An owner subclasses `SemanticRequest`, enumerating every consequential field and
normalizing it through its typed validators. Use concrete generic parameters for
`CommandIntent[OwningRequest]`, `CommandEnvelope[OwningRequest]` and
`OperationOutcome[OwningResult]`; `OwningResult` is also a declared `SemanticRequest`
record. Extra fields are forbidden, models frozen and integers strict. Nested records
must derive from `Contract`; arrays are immutable tuples with meaningful ordering.
Mappings, mutable lists, floating point, bytes and secret wrappers are rejected.
Do not declare secret/plaintext business-content fields in a hosted operational record:
type validation is not a secret scanner, owning allowlists remain necessary.

`canonical_bytes(intent)` is the persistence/hash representation, not a general
Pydantic serialization or arbitrary input dictionary. It includes all declared fields,
even fields a serializer would exclude, sorts object keys, preserves array order,
uses compact UTF-8 JSON and limits the complete record to 16 KiB and nesting to 16.
Integers use signed-64-bit bounds; numeric money values remain integers. Owners own
Unicode/text normalization; the shared hash must not reinterpret opaque identifiers.

Defaults are consequential and included. An omitted field with a default and the
same explicitly supplied value have the same hash; a default `None` is JSON `null`.
Null differs from empty text. If omission and null have different effects, model that
as explicit tagged intent variants. The fixed vectors in the focused tests freeze
these rules, including normalized Unicode. No unspecified transport field is removed
from an action payload by name.

`CommandIntent` adds deployment, workspace/deployment scope, action kind, component
when applicable, expected revision and access epoch to the hash. Owning payloads must
also include selected release/resource IDs, initial-data/seed identity, capacity
commitments and every other consequential parameter. H01.4 defines actual action
contracts; the tests' provisioning payload is a synthetic fixture, not production policy.

Operation ID/idempotency key identify the lookup, not its semantic content. The only
volatile metadata envelope is `TransportMetadata` (correlation ID/sent-at), outside
intent and its hash. The supplied hash is always checked against validated intent.
Store canonical intent and hash together; never reconstruct old intent from current
assignments. No raw tokens, passwords, cookies, provider payloads or shell output
belong in persisted intent/result/audit. Registered references are opaque IDs, not
caller-selected locators; owning ports still resolve and authorize them.

## Outcomes, original lookup and HTTP boundary

All six operation states are explicit. Only success may contain a committed result;
it requires that original typed result and no error/action code. Failed and
needs-attention states require a classified error; unknown and needs-attention
require an explicit next action. Pending/running cannot claim failure or action
requirements. These are snapshot invariants, not a persistent transition engine.

`original_result(command, retained)` compares deployment, scope, kind, key and hash.
A matching retry returns the supplied original object/operation ID, even if the retry
proposed another operation ID. Changed intent or mismatched lookup raises the safe
`hosted_operation_conflict` code. A missing receipt returns `None`; this grants no
permission to dispatch or reserve a fresh effect. Authentication, lookup ownership,
atomic unique-key reservation, current fences and effect reconciliation remain the
owning repository/service's obligations. This function provides no durable deduplication.

`transport_timeout` creates an unknown observation requiring `check_original_result`;
it cannot mutate a retained success, fabricate a failed effect or authorize replay.
Types are frozen, but repository-level terminal-result immutability remains a later proof.

Use existing `platform.api_errors.domain_problem` at router boundaries (semantic
conflict 409), and its shared `validation_problem` for malformed typed input (422)
or size bounds (413). Canonical byte overflow uses Pydantic's standard `too_long`
classification. No HTTP status policy or FastAPI import lives in this package.

## Reads and continuation

`Freshness` distinguishes known/stale observations with source revision/capture from
unknown/unavailable responses requiring a safe reason and no fabricated capture.
Owning reads keep last-known data separately when needed; absence is not usage zero.
`ContinuationCursor` pins deployment, scope, endpoint, filter hash, capture, source
revision and ordering version. It bounds pages to 1–50 and ordering positions to
1–8 strings of up to 1,024 characters, allowing human-name sort keys. Those strings
are ordering data, not resource locators. A changed context requires a fresh restart.

This is a typed internal envelope, not an opaque encoder, signature, authentication
proof, snapshot query or pagination implementation. Owning adapters must validate
trusted capture/source context, authorize scope, encode/verify bounded opaque tokens
and execute bounded queries. No schema, runtime, provider or UI gate is enabled here.
