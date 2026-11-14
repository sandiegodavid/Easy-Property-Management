# H03.7 destination handoff

H03.7 implements and locally validates the destination browser challenge,
Ed25519 pairing assertion, one-use central handoff and source-owned session
issuance. Initial start carries public flow and registered-origin selectors.
The central owner resolves the selected source through protected registration.
The protected source challenge and signed handoff travel in cookies and POST
bodies. Google issuance requires the stored managed proof for the exact central
attempt. Email return requires the completing browser and the observed new
destination challenge.

The central store reserves redemption before the source writes. The source checks
current ownership and access fences and commits the session hash, attempt
completion, audit and original receipt together. The central owner acknowledges
the observed source receipt after that transaction. A repeat or a lost response
can reconcile the original receipt. Only the original successful callback emits
the Operator session cookie.

The H03.6 source relay supports typed attempt and receipt inspection. The
source-scoped reverse channel supports continuation lookup, reservation and
acknowledgement. The Operator composition runs the private listener inside the
public process's writer lifetime. The new composition admits the three auth
paths. Business request admission remains unavailable pending H03.10.

## Local validation

360 focused Python tests and five central sign-in Playwright tests passed.
Changed-file Ruff lint and formatting, frontend lint, formatting and type
checking, and Git whitespace checks passed.

| Area | Observed evidence |
| --- | --- |
| Browser binding | Four independent HTTP client cookie jars, a real SQLite owner on each side and an Ed25519-signed email round trip. Concurrent completion of one email code produced one winner. Swapped browser cookies and the wrong callback origin were rejected. |
| Google return | An exact completed-attempt/proof cookie match is required. The browser continuation uses a native POST, and replay cannot reissue a handoff or source bearer. |
| Persistence and reconciliation | Rollback after injected receipt failure, disabling access after reservation, lost acknowledgement and late acknowledgement of the original receipt. The installed greenfield schema validates the committed records. |
| Runtime boundary | Unix socket round trip through both relay directions, current source lookup and refusal when the Operator writer is unavailable. This uses local peers with a synthetic deployment binding. |

[H03.8](HOSTED_MVP_H03_8_CHECKPOINT.md) delivers ongoing authorization, renewal and source lifecycle operations.
H03.11 installs the authentication candidates and supplies the protected
binding registry, signing keys, socket endpoints and peer identities. H03.12
qualifies the deployed HTTPS and provider flow. Production activation and
initial assignment readiness still depend on the H04/H05 owners.
