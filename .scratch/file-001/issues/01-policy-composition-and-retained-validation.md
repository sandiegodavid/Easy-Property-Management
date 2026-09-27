# FILE-001 issue 01 — policy composition and retained validation

Type: task
Status: resolved
Blocked by:

## Answer

Owning-domain file policies are composed at the bootstrap boundary through
explicit, shape-compatible fact adapters. Current-schema, restore, and backup
validation receive that same registry, fail closed for unknown entity types,
and validate each policy's retained aggregate limit.
