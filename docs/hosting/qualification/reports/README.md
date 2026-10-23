# Supporting qualification reports

These are dated technical records, not the current rollout checklist. Start with the
[qualification register](../HOSTED_DEMO_PUBLIC_ACCESS_PLAN.md) for current status.

| Report | What it establishes |
| --- | --- |
| [Linux quota](HOSTED_DEMO_LINUX_QUOTA_2026-10-23.md) | Unprivileged SQLite FULL, rollback and retained recovery space on a bounded image |
| [Systemd and uploads](HOSTED_DEMO_SYSTEMD_UPLOAD_2026-10-23.md) | Service sandbox, actual multipart admission, byte integrity and original-result reads |
| [R2 recovery and remount](HOSTED_DEMO_RECOVERY_2026-10-23.md) | Real encrypted off-host round-trip, complete retained-data/file comparison and a fresh bounded restore |
| [Installed release and boot](HOSTED_DEMO_INSTALLED_RELEASE_2026-10-23.md) | Combined artifact, service environment, exact mount and approved scratch boot checks |
| [Cost/latency planning basis](HOSTED_DEMO_COST_LATENCY_REVIEW_2026-10-23.txt) | Accepted optimization choices and measurement requirements; no live benchmark |

Each report identifies its fixture, release, result and limits. Raw before/after
observations remain under [evidence](../../evidence/); full original narrative is preserved
in the [planning/report archive](../../archive/planning-and-reports-2026-10-24/).
