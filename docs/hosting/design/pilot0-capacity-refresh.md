# Pilot 0 capacity snapshot refresh

Proposed for review. No timer, service, or code changes are deployed.

Pilot 0 admission currently depends on a manually refreshed host snapshot. Demo C was blocked when the observation aged past the profile’s 24-hour threshold. Refresh automation should keep measurements current while preserving the existing fail-closed admission behavior.

Use a host-local systemd timer to run the same one-shot refresh used by operators. Start about two minutes after boot and repeat every 15 minutes while the VM runs. A host-local timer can read Linux cgroups, the mounted filesystems and quota accounting, and report failures to the journal. Cloud Monitoring alone can alert on host headroom but does not produce the per-Operator observations or reconcile the Admin ledger.

The collector should take bounded readings outside the Admin transaction. Resolve Operator identities from trusted host inventory, verify container and filesystem ownership, and reconcile active and retained allocations with the Admin ledger. Account conservatively for unattributed consumption. If a mount, container, commitment, or metric cannot be reconciled, fail the run. Reserve changes remain an explicit profile registration operation.

The publisher should use the Admin capacity store through a narrowly scoped host entry point. Serialize refresh runs, recheck the starting profile, snapshot and commitment revisions inside the write transaction, and persist the new observations and snapshot together. Discard a sample if concurrent admission or rollout changed its inputs. Use the actual collection time and preserve the prior snapshot on failure. Monitor both run failures and elapsed time since the last successful refresh so a missed run is detectable. Admission remains the only path that reserves resources.

| Slice | Acceptance and validation |
| --- | --- |
| 1. One-shot collection | Dry run on GCP agrees with manual cgroup, disk/inode and quota readings. Test missing mounts, missing metrics, retained allocations, unknown containers, and usage above a commitment. |
| 2. Atomic publication | Tests prove monotonic revisions, rejection of a stale sample after admission or profile switch, rollback on partial failure, and unchanged reserve limits. |
| 3. Timer and observability | Verify boot and periodic runs, no overlap, and alerting for repeated failures or a stale snapshot. Prove a failing refresh cannot reopen admission. Disable the timer to return to the [manual workflow](../operations/pilot0-admission-and-incidents.md#refresh-or-revise-host-capacity). |
