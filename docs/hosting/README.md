# Hosting documentation — review index

Consolidated October 24, 2026. This set covers local operation, the two-operator
synthetic hosted demo and the planned hosted MVP. US customers/properties are the
product scope; no additional data-residency requirement is imposed.

## Current demo in one page

- **Host:** Google Cloud `epm-demo`, `us-west1-b`, E2 medium/4 GB, Ubuntu 24.04
  x86_64, 30 GB disk; administrator SSH through IAP only.
- **Isolation:** separate Unix identities, one process/writer and fully allocated
  250 MiB workspace image each; local SQLite/evidence, 50 MiB per-file limit.
- **Access:** exact `demo-a.epmdemo.xyz` and `demo-b.epmdemo.xyz`, Cloudflare email
  PIN plus approved subject/application session. Both intended accounts active;
  Home, policy matrix, device and multi-session logout passed as recorded.
- **Runtime:** `signin-nav-20261024`, Python 3.14.9/package 0.1.0; old qualified
  runtime retained. Hosted units active/enabled; old local units masked. Tunnel
  active for acceptance but **disabled at boot**. General invitations pending.
- **Recovery:** fresh A/B business archives verified through real R2 restore;
  current-binding administrator references separately encrypted and verified.
  Manual daily backups/seven successful UTC days; no unattended keyring/cron claim.
- **Funding:** trial ends January 22, 2027 and $30 alerts configured per operator;
  review funding by January 15. $30/month is a target, not a cap or price quote.
- **Next:** prepared synthetic Task persistence/foreign-record test remains
  unreported. Actual file/receipt/concurrency/cache/performance/final boot/outage
  gates still apply. See the qualification plan for the one current checkpoint.

## Reading order and document ownership

| Read | Purpose / owner of information |
| --- | --- |
| [Hosting Plan](Hosting_Plan.md) | Product-level local/demo/hosted-MVP choices and later commercial gaps |
| [Hosted demo design](design/HOSTED_DEMO_DESIGN.md) | Accepted scope, architecture, security, resource/cost/latency requirements and delivery boundaries |
| [Additional operators and Admin console proposal](design/HOSTED_DEMO_ADMIN_DESIGN.md) | Proposed expansion beyond A/B: capacity qualification, private Admin workflow/UI, provisioning, access lifecycle and backend/tooling changes; not deployed |
| [Deployment guide](deployment/GOOGLE_CLOUD_DEMO_DEPLOYMENT.md) | Google VM/IAP, reproducible release, volumes, Cloudflare and enrollment setup; new-resource commands |
| [Configuration contract](deployment/HOSTED_DEMO_CONFIGURATION.md) | JSON fields, route/capability inventory, owner CLI, session and edit-lease rules |
| [Administrator runbook](operations/HOSTED_DEMO_OPERATIONS.md) | Daily inspection/backups, credentials, disable/renew/reset, host-loss recovery and rollback |
| [Ongoing Google Cloud runbook](operations/GOOGLE_CLOUD_ONGOING_RUNBOOK.md) | After-setup quick reference and replacement-release build/upload/switch/rollback sequence |
| [Operator guide](operations/HOSTED_DEMO_OPERATOR_GUIDE.md) | Assigned sign-in, session controls, multiple devices, saved forms and safe recovery |
| [Qualification and rollout plan](qualification/HOSTED_DEMO_PUBLIC_ACCESS_PLAN.md) | **Single current checkpoint**, passed scope, remaining gates, test matrix and completion criteria |
| [Cloudflare/VM operations record](operations/CLOUDFLARE_OPERATIONS.md) | Current exact inventory, completed setup sequence and cumulative future operation entries |
| [Supporting reports](qualification/reports) / [raw evidence](evidence) | Dated focused Linux/upload/recovery/build reports and machine-readable results |
| [Source archive](archive/README.md) | All pre-consolidation details and historical PDF exports; context rather than current instructions |

## Evidence and maintenance rules

Design requirements, operating procedures and observed evidence are distinct.
Use operator-reported/injected/physical qualifiers, preserve exact evidence dates
and limits, and do not infer completed gates from a reachable page or successful
connector. Put actual secrets/emails/AUDs/passphrases only in protected deployment
inputs; public examples use placeholders. Source archive preserves every original
detail, while current pages use the latest accepted decisions and deployment state.

When progressing setup, append the operation once to the cumulative record and
replace the qualification checkpoint rather than accumulating competing handoffs.
Record new checksums for changed artifacts; never silently promote planned tests
or stale recovery-age observations into current verified results.
