# Hosted operator project quotas

November 1, 2026

This technical research supports [Hosted Admin Slice 8](../hosting/design/HOSTED_DEMO_ADMIN_DESIGN.md). It does not establish that the Google demo filesystem supports or currently enforces project quotas. No live host changes were performed.

## Feasibility

Linux supports per-project filesystem limits through `PRJQUOTA`. Hard limits prevent further charged allocation; soft limits allow a grace period. Use hard block and inode limits for isolation, with application warnings rather than relying on soft-limit grace. Updating a project limit does not resize the underlying filesystem. The block and inode limits are distinct. [Linux quotactl interface](https://man7.org/linux/man-pages/man2/quotactl.2.html), [quota data fields](https://man7.org/linux/man-pages/man2/dqblk.2type.html).

Ext4 supports project IDs and internal quota inodes. The installed kernel, e2fsprogs version, inode format, filesystem features and enforcement state all matter: a directory naming convention or `prjquota` text in configuration is not proof of enforcement. `tune2fs` exposes `project`, `quota` and the project-quota inode setting; project IDs require sufficiently large inodes. [Upstream tune2fs manual](https://man7.org/linux/man-pages/man8/tune2fs.8.html). An operational distribution procedure includes project-quota filesystem initialization and activation. [Red Hat ext4 quota administration](https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/8/html/managing_file_systems/limiting-storage-space-usage-on-ext4-with-quotas_managing-file-systems).

**Design inference:** prefer one qualified shared EPM data filesystem with private operator directories over an individual filesystem per operator. Inspect the existing filesystem first. If it needs feature changes, unmounting or reboot, perform a separately reviewed host-wide maintenance procedure; ordinary Add operator must never alter the root filesystem's features or format a device. Do not introduce application-only enforcement as an automatic fallback when project enforcement is unavailable.

## Directory inheritance and tamper resistance

An ext4 directory's `P` attribute makes newly created children inherit its project ID and restricts cross-project renames and hard links. Changing a populated directory's project alone is not a recursive conversion of its existing contents; provisioning/restore must verify descendants and create new content under the destination project. [Upstream chattr manual](https://man7.org/linux/man-pages/man1/chattr.1.html).

**Important security finding:** Unix ownership and removal of `CAP_SYS_ADMIN` alone are insufficient proof that an application cannot escape its project. In Linux v6.12, generic file-attribute handling accepts inode-owner calls and permits project-ID/inheritance changes in the initial user namespace; a noninitial user namespace is restricted from changing those values. This is version-specific evidence, so qualify the deployed kernel rather than assuming an invariant. [Linux v6.12 file-attribute implementation](https://raw.githubusercontent.com/torvalds/linux/v6.12/fs/ioctl.c).

**Design inference:** the service sandbox must deny project-ID/inheritance mutation interfaces, including applicable compatibility/newer interfaces, or use another verified kernel isolation mechanism. Test attempted changes directly as the actual application identity, not merely absence of `chattr` from its PATH. Keep quota-setting authority in the private broker. Test child directories, moved/restored files, same-filesystem hard links, project-zero escape, writable temporary paths and inherited file descriptors. Keep each operator's ordinary permissions private; project quota is resource accounting, not a read-access control.

## Usage, reserves and failure behavior

Kernel quota usage reports occupied bytes and allocated inode counts. This is different from summing file logical lengths or counting application attachments. Sparse files, database journals, deleted-but-open files and temporary copies require qualification against kernel accounting. Do not use filesystem-wide `df`/`statvfs` values as an operator's remaining quota. A privileged collector can obtain project usage and publish a narrowly scoped snapshot; the business process does not need broad quota-inspection authority. [Quota structure](https://man7.org/linux/man-pages/man2/dqblk.2type.html), [quota-read privilege boundary](https://man7.org/linux/man-pages/man2/Q_GETQUOTA.2const.html).

**Design inference:** a project limit caps consumption; it does not preallocate space or promise that all operators can reach their limits. Admission must separately reserve aggregate worst-case project growth, temporary processing, access/control storage, logs, backups and host emergency headroom. Changing from fully allocated images removes their implicit preallocation; retaining conservative host admission is essential. Filesystem metadata and its global journal remain shared costs. Logical usable-workspace allowances therefore need separately defined application accounting, or the UI must instead explicitly describe a whole-project allocated-storage budget.

Linux writes can partially succeed, and quota or physical-space failure can surface during writes or later synchronization. Preserve application atomicity, staging cleanup and uncertain-result lookup; do not treat an initial write result as proof of durable publication. Distinguish `EDQUOT` from underlying `ENOSPC` and provide safe typed application errors. [Linux write semantics](https://man7.org/linux/man-pages/man2/write.2.html).

Qualification must test block and inode exhaustion, concurrent upload reservations, database commit/checkpoint failure, root-created files' project attribution, quota persistence after reboot, disabled enforcement, shared-host disk exhaustion, private backups/restores and quota-change crash reconciliation. A quota decrease below current usage may be technically representable but is a poor operator workflow: reject it before mutation and show the required cleanup or larger tier.
