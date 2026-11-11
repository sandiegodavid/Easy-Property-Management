# H01.6 action delivery mapping

Generated from the typed fixture composition registry; this is a handoff table,
not an endpoint/permission registry. No action is dispatched by these fixtures.
H03–H05 own the usable end-to-end workflow and actual current authorization.

| UI action key | Owning port / method | Command / lookup | Authority | Confirmation | Response / identity | Delivery |
| --- | --- | --- | --- | --- | --- | --- |
| `admin_create_assignment` | `AdminPort.execute` | `CreateAssignment` | `admin_recent_mfa` | `review_form` | `operation` / `new_original` | H04 |
| `admin_provision` | `AdminPort.execute` | `Provision` | `admin_recent_mfa` | `explicit_action` | `operation` / `new_original` | H04 |
| `admin_check_operation` | `AdminPort.original` | `own scoped lookup` | `admin_recent_mfa` | `none` | `operation` / `existing_original` | H04 |
| `admin_retry_operation` | `AdminPort.execute` | `retain original command` | `admin_recent_mfa` | `explicit_action` | `operation` / `existing_original` | H04 |
| `admin_refresh_source` | `AdminPort.execute` | `RefreshSource` | `admin_recent_mfa` | `none` | `operation` / `new_original` | H04 |
| `admin_reissue_invitation` | `AdminPort.execute` | `ReissueInvitation` | `admin_recent_mfa` | `explicit_action` | `operation` / `new_original` | H04 |
| `admin_disable` | `AdminPort.execute` | `Disable` | `admin_recent_mfa` | `explicit_action` | `operation` / `new_original` | H04 |
| `admin_enable` | `AdminPort.execute` | `Enable` | `admin_recent_mfa` | `explicit_action` | `operation` / `new_original` | H04 |
| `admin_rebind` | `AdminPort.execute` | `Rebind` | `admin_recent_mfa` | `explicit_action` | `operation` / `new_original` | H04 |
| `admin_prepare_retirement` | `AdminPort.execute` | `PrepareRetirement` | `admin_recent_mfa` | `explicit_action` | `operation` / `new_original` | H04 |
| `admin_confirm_retirement` | `AdminPort.execute` | `ConfirmRetirement` | `admin_recent_mfa` | `exact_preview_intent` | `operation` / `new_original` | H04 |
| `admin_repair_runtime` | `AdminPort.execute` | `RepairRuntime` | `admin_recent_mfa` | `explicit_action` | `operation` / `new_original` | H04 |
| `admin_announce_maintenance` | `AdminPort.execute` | `AnnounceMaintenance` | `admin_recent_mfa` | `review_form` | `operation` / `new_original` | H04 |
| `admin_maintenance_release` | `AdminPort.execute` | `MaintenanceRelease` | `admin_recent_mfa` | `explicit_action` | `operation` / `new_original` | H04 |
| `admin_preview_control_restore` | `AdminRecoveryPort.execute` | `PreviewControlRestore` | `protected_bootstrap_mfa` | `explicit_action` | `operation` / `new_original` | H05 |
| `admin_confirm_control_restore` | `AdminRecoveryPort.execute` | `ConfirmControlRestore` | `protected_bootstrap_mfa` | `exact_preview_intent` | `operation` / `new_original` | H05 |
| `operator_read_settings` | `SourcePort.observe` | `bounded current read` | `current_operator` | `none` | `bounded_read` / `read_only` | H04 |
| `operator_list_points` | `WorkspaceRecoveryPort.observe` | `bounded current read` | `current_operator` | `none` | `bounded_read` / `read_only` | H05 |
| `operator_preview_restore` | `WorkspaceRecoveryPort.execute` | `PreviewRestore` | `current_operator` | `review_form` | `operation` / `new_original` | H05 |
| `operator_recent_authenticate` | `LoginPort.execute` | `RecentAuthenticate` | `managed_recent_auth` | `explicit_action` | `operation` / `new_original` | H03 |
| `operator_confirm_restore` | `WorkspaceRecoveryPort.execute` | `ConfirmRestore` | `operator_strong_step_up` | `exact_preview_intent` | `operation` / `new_original` | H05 |
| `operator_check_restore` | `WorkspaceRecoveryPort.original` | `own scoped lookup` | `current_operator` | `none` | `operation` / `existing_original` | H05 |

Authority requirements are not user-editable claims. Referenced managed/channel/MFA
proofs, source epochs, scope and resource readiness must be verified by the owning
application adapters. In particular, `current_operator` on Settings describes the
consumer boundary before the private source-service observation; it is not an
Operator actor passed directly to `SourcePort.observe`.

`existing_original` always keeps the original operation/key/semantic intent. A
transport timeout remains unknown until inspection; no new dispatch identity is
created by Check or Retry. `new_original` means a deliberately reviewed new command,
not an automatic retry. `operation` responses retain pending/running/unknown states;
`bounded_read` never converts missing data to zero or authorizes mutation.

The two control-restore entries are H05 mappings for a separate Admin recovery
entry point. They are not rendered by operator Admin-detail snapshots or Settings.
Current protected bootstrap/MFA is independent of ordinary/restored Admin sessions.
H04/H05 validate exact preview/point/resource IDs and current fences at submit; the
table and fixture booleans are not grant evidence.
