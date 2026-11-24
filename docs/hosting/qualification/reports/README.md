# Hosted MVP Qualification Reports

This directory retains **only** the live Pilot 0 (`H06.10`) GO evidence, active 4-week cost/operations worksheet, and machine-checked sizing baselines referenced by automated tests. Historical intermediate slice checkpoints (`H01–H06.9`) are preserved in Git history rather than duplicated here.

| Report | Role |
| --- | --- |
| [HOSTED_MVP_H06_10_EXIT_REVIEW.md](HOSTED_MVP_H06_10_EXIT_REVIEW.md) | Pilot 0 GO exit review summarizing all 6 live GCP launch-day gates and pinned artifact digests. |
| [PILOT_0_COST_AND_OPS_WORKSHEET.md](PILOT_0_COST_AND_OPS_WORKSHEET.md) | Active 4-week Pilot 0 cost, Admin-minutes, and repeat-use adoption tracker (also loaded by `qualify_h06_pilot0.py`). |
| [HOSTED_MVP_H06_10_DOCKER_LINUX_IMAGE_SCHEMA.json](HOSTED_MVP_H06_10_DOCKER_LINUX_IMAGE_SCHEMA.json) | Gate 2: Immutable `docker_linux` OCI image digests and zero-checkout 6-store verification. |
| [HOSTED_MVP_H06_10_LIVE_OBSERVABILITY.json](HOSTED_MVP_H06_10_LIVE_OBSERVABILITY.json) | Gate 3: Live GCP monitoring channel, 7 alert policies, 3 log-based metrics, uptime check, `$250/mo` budget, and Ops Agent proof. |
| [HOSTED_MVP_H06_10_GCP_RECOVERY_17.json](HOSTED_MVP_H06_10_GCP_RECOVERY_17.json) | Gate 4a: Live GCP 17-case `recovery.json` + joint H04/H05 positive handoff proof. |
| [HOSTED_MVP_H06_6_LIVE_R2_KMS_RECOVERY.json](HOSTED_MVP_H06_6_LIVE_R2_KMS_RECOVERY.json) | Gate 4b: Live Cloudflare R2 + GCP Cloud KMS + `SO_PEERCRED` `epm-backup-proxy` end-to-end recovery proof. |
| [HOSTED_MVP_H06_10_DEPLOYED_BROWSER_IDENTITY.json](HOSTED_MVP_H06_10_DEPLOYED_BROWSER_IDENTITY.json) | Gate 5: Live deployed 4-browser `identity_handoff.json` proof on `admin.epmdemo.xyz` and `login.epmdemo.xyz`. |
| [HOSTED_MVP_H06_10_GCP_OPERATIONS_ECONOMICS.json](HOSTED_MVP_H06_10_GCP_OPERATIONS_ECONOMICS.json) | Gate 6: Live GCP Linux 9-case `operations_economics.json` proof. |
| [HOSTED_MVP_H04_9_FREE_SIZING.json](HOSTED_MVP_H04_9_FREE_SIZING.json) | Pinned Free 50 MB `ext4 prjquota` sizing baseline (loaded by `test_h04_handoff_qualification.py` and `test_h05_sizing_qualification.py`). |
| [HOSTED_MVP_H05_9_RECOVERY_SIZING.json](HOSTED_MVP_H05_9_RECOVERY_SIZING.json) | Pinned H05.9 backup/restore reserve sizing baseline (loaded by `qualify_h06_pilot0.py`). |
