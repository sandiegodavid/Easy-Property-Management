# Hosting qualification

Qualification register, machine-validated proof specifications, UI contract fixtures, and
latest exit reviews for **HOSTED-001**.

## Core References

- [MVP acceptance register](HOSTED_MVP_ACCEPTANCE.md): authoritative release-proof gates across H01–H06.
- [Latest reports & exit reviews](reports/README.md): pinned H01–H04 handoff reports, Free sizing measurements, and native GCP evidence.
- [Proof specifications](specifications/README.md): six machine-validated proof specs (67 required cases) + [report format](specifications/REPORT_FORMAT.md) and [packaging handoff](specifications/PACKAGING_HANDOFF.md).
- [UI/API contract fixtures](fixtures/README.md): 24 frozen contract snapshots (`H01_UI_CONTRACTS.json`) and [action map](fixtures/ACTION_MAP.md).

## Current Qualification State (2026-11-22)

| Slice | Qualified Scope | Latest Report |
| --- | --- | --- |
| **H01** | Schema resources, typed contracts, proof validator, UI contract fixtures | [H01.7 handoff](reports/HOSTED_MVP_H01_7_HANDOFF_2026-11-11.md) |
| **H02** | Native Linux/Docker/GCP `prjquota`, network containment, warm-capacity profile, reboot closure | [H02.11 handoff](reports/HOSTED_MVP_H02_11_HANDOFF.md) |
| **H03** | Component proof (14/14 cases), Lima native gateway/reboot/network, GCP live Google+TOTP MFA & outage deadlines, sealed `selection.json` | [H03.12 exit review](reports/HOSTED_MVP_H03_12_EXIT_REVIEW_2026-11-22.md) |
| **H04** | Native GCP Free 50 MB physical sizing (`162 MiB / 5,376 inodes` workspace, `18 MiB / 768` control, `33 MiB / 768` scratch) + 2-operator closed-handoff proof | [H04.10 exit review](reports/HOSTED_MVP_H04_10_EXIT_REVIEW_2026-11-22.md) |
| **H05+** | Off-host backup/restore qualification, backup/restore physical reserve, and positive eligible-ingress handoff | **Open (next)** |

Mocked, component, native Linux, and deployed GCP results are always recorded separately
with exact dates, artifact digests, and remaining gates.
