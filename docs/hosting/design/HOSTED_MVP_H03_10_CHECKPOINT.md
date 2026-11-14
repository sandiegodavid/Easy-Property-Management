# H03.10 managed business and draft admission

H03.10 is delivered and locally validated. The protected managed composition
checks source sessions, allowed routes, Origin, CSRF, and storage admission.
Deployment packaging and registration remain H03.11. Deployed browser,
provider, and native qualification remain H03.12. The protected owner and the
H04/H05 gates are required before enabling deployed business access.

## Behavior

- Editing authority is scoped to a form, session hash, access epoch, and
  restore generation. Taking over a form requires its current saved revision.
  Distinct forms can be edited independently.
- A shared process gate orders source revocation and workspace writes. Source
  authority is checked before writing and again before commit. Each store
  uses its own transaction.
- Managed receipt guards identify prepared operations by the owning receipt
  namespace and durable attempt key. Only a valid lease for that attempt's
  saved form authorizes the insert. Local Operator composition and portable
  workspace backups use the existing durable closure guards.
- Multipart handlers keep blocking staging and writes off the API event
  loop. A device can revoke an in-flight uploader; the owning transaction
  rechecks authority and cleans up abandoned content on rejection.
- Session rotation invalidates pending claim responses. An operator must
  explicitly claim the edit lease again. A delayed save or preparation
  cannot continue an older submit after rotation. An interrupted command
  stays unresolved until the operator checks or explicitly retries the original.

## Focused validation

| Area | Local evidence |
| --- | --- |
| Admission and lease | Identity-only mode remains closed to business routes. Managed requests check the registered HTTPS origin and CSRF. Omitted or wrong-form claims roll back prepared task writes. A valid lease commits once. Tests cover takeover, independent claims, and restore fencing. |
| Rollback and original result | Session expiry after the task receipt insert rolls back the transaction. A real multipart upload revoked after filesystem staging returns 401, removes the staged file, and creates no receipt even when central revocation acknowledgment is unavailable. The still-authorized device claims the form, retries the original key, and reconciles its receipt. |
| Browser | Eight recovery tests and four managed security tests pass. They cover delayed claims, delayed save acknowledgments across rotation, explicit continuation, device revocation, and existing local recovery. |
| Persistence and bounds | 223 focused Python tests pass across source sessions, schema, local inventory and form recovery, and file, Intake and inspection commands. The tests cover a single indexed source read for admission, bounded recovery queries, and backup/restore. |
| Build and static checks | The web wheel was rebuilt locally and the recovery server verified that its assets matched the current Vite build. Ruff, frontend lint, formatting and type checks, generated-contract reproducibility, and Git whitespace checks pass. |
