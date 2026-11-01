import { useId, useState } from "react";
import type { components } from "../../../../packages/contracts/src/generated/admin-schema";
import { useRead, time, words } from "./reads";
import { Submission } from "./upgrades";

type Command = components["schemas"]["BatchCommand"];
type View = components["schemas"]["BatchView"];
type Directory = components["schemas"]["BatchDirectory"];
type Release = components["schemas"]["InstalledRelease"];
export type SelectedOperator = {
  key: string;
  name: string;
  revision: number;
  release?: string;
  access?: string;
};
const selectionKey = "epm-admin-upgrade-selection";
function loadSelection(): SelectedOperator[] {
  try {
    const value: unknown = JSON.parse(sessionStorage.getItem(selectionKey) ?? "[]");
    return Array.isArray(value)
      ? value
          .filter((item: unknown): item is SelectedOperator => {
            if (!item || typeof item !== "object") return false;
            return (
              "key" in item &&
              typeof item.key === "string" &&
              /^[a-z0-9][a-z0-9-]{0,31}$/.test(item.key) &&
              "name" in item &&
              typeof item.name === "string" &&
              item.name.length <= 255 &&
              "revision" in item &&
              typeof item.revision === "number" &&
              Number.isInteger(item.revision) &&
              item.revision > 0 &&
              (!("release" in item) || typeof item.release === "string") &&
              (!("access" in item) || typeof item.access === "string")
            );
          })
          .slice(0, 50)
      : [];
  } catch {
    return [];
  }
}
export function useUpgradeSelection() {
  const [selected, setSelected] = useState(loadSelection);
  function save(items: SelectedOperator[]) {
    const unique = items
      .filter((item, index) => items.findIndex((other) => other.key === item.key) === index)
      .slice(0, 50);
    setSelected(unique);
    try {
      sessionStorage.setItem(selectionKey, JSON.stringify(unique));
    } catch {
      /* Current page remains usable if browser storage is unavailable. */
    }
  }
  return { selected, save };
}
function base(action: Command["action"], batch?: View): Command {
  return {
    id: crypto.randomUUID(),
    action,
    batch: batch?.id ?? null,
    expected_revision: batch?.revision ?? null,
    members: [],
    release: null,
    sessions: [],
    window_start: null,
    window_end: null,
    instance: null,
    confirmed: action !== "check" && action !== "recheck",
    reason: "Reviewed operator release batch",
  };
}

function NewBatch() {
  const [members, setMembers] = useState(loadSelection);
  return (
    <>
      <h1>Upgrade operators</h1>
      <p>
        Select up to 50 registered operators. They will be upgraded one at a time; qualification and
        hosting capacity still apply.
      </p>
      {members.map((item, index) => (
        <article className="item" key={item.key}>
          <h2>{item.name}</h2>
          <p>
            Release at selection: {item.release ?? "Not yet checked"} · Access:{" "}
            {item.access ?? "Unknown"}
          </p>
          <p>
            Position {index + 1} of {members.length}
          </p>
          <div className="actions">
            <button
              disabled={index === 0}
              onClick={() =>
                setMembers((prior) => {
                  const copy = [...prior];
                  [copy[index - 1], copy[index]] = [copy[index], copy[index - 1]];
                  return copy;
                })
              }
            >
              Move {item.name} earlier
            </button>
            <button
              disabled={index === members.length - 1}
              onClick={() =>
                setMembers((prior) => {
                  const copy = [...prior];
                  [copy[index + 1], copy[index]] = [copy[index], copy[index + 1]];
                  return copy;
                })
              }
            >
              Move {item.name} later
            </button>
            <button
              onClick={() => setMembers((prior) => prior.filter((other) => other.key !== item.key))}
            >
              Remove {item.name}
            </button>
          </div>
        </article>
      ))}
      {members.length ? (
        <ReleaseChoice key={members.map((item) => item.key).join(",")} members={members} />
      ) : (
        <p>Select operators from the directory first.</p>
      )}
    </>
  );
}
function ReleaseChoice({ members }: { members: SelectedOperator[] }) {
  const options = useRead<{ items: Release[] }>(
    `/admin-api/operators/${members[0].key}/upgrade-options`,
  );
  const [command, setCommand] = useState<Command>();
  return (
    <section className="panel">
      <h2>Check the target release</h2>
      <p>
        Choices come from the first operator. Readiness checks every selected operator independently
        without interrupting access.
      </p>
      {options.failed && (
        <p role="alert">
          Release choices are unavailable. Check the private connection and qualification reports.
        </p>
      )}
      <label htmlFor="bulk-release">Installed target release</label>
      <select
        id="bulk-release"
        disabled={options.failed}
        value={command?.release ?? ""}
        onChange={(event) =>
          setCommand(
            event.target.value
              ? {
                  ...base("check"),
                  release: event.target.value,
                  members: members.map((item) => ({
                    instance: item.key,
                    expected_revision: item.revision,
                  })),
                }
              : undefined,
          )
        }
      >
        <option value="">Choose a release…</option>
        {options.data?.items.map((item) => (
          <option key={item.release} value={item.release} disabled={!item.eligible}>
            {item.release}
            {item.eligible ? "" : " — Unavailable"}
          </option>
        ))}
      </select>
      {options.data?.items.flatMap((item) =>
        item.blockers.map((reason) => (
          <p key={`${item.release}:${reason}`}>
            {item.release}: {reason}
          </p>
        )),
      )}
      {command && (
        <Submission
          key={command.id}
          command={command}
          title="Check batch readiness"
          credentialRequired={false}
        />
      )}
    </section>
  );
}
function BatchDecision({ view }: { view: View }) {
  const [handling, setHandling] = useState<Record<string, "preserve" | "revoke">>(() =>
    Object.fromEntries(
      view.items.map((item) => [
        item.instance,
        item.session_handling ?? (item.preserve_sessions ? "preserve" : "revoke"),
      ]),
    ),
  );
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [reviewed, setReviewed] = useState<Command>();
  const id = useId();
  const hasRun = view.window_start !== null;
  const ready = view.state === "ready";
  const cancelled = view.state === "cancelled";
  function review(action: Command["action"], instance?: string) {
    const command = { ...base(action, view), reason: reason.trim() };
    if (action === "start" || action === "resume") {
      command.sessions = view.items.map((item) => ({
        instance: item.instance,
        handling: handling[item.instance],
      }));
      command.window_start = new Date(start).getTime() / 1000;
      command.window_end = new Date(end).getTime() / 1000;
    }
    if (action === "skip") command.instance = instance ?? null;
    setReviewed(command);
  }
  if (reviewed)
    return (
      <section className="panel">
        <h2>Confirm batch decision</h2>
        <p>
          {words(reviewed.action)} · {view.total} selected operators · {view.release}
        </p>
        <p>Reason: {reviewed.reason}</p>
        {reviewed.action === "skip" && (
          <p>
            Skip{" "}
            {view.items.find((item) => item.instance === reviewed.instance)?.name ??
              reviewed.instance}
            . If this operator already started, it will be fenced and containment must verify before
            the queue can resume. Skipping retains its history and can leave access paused for
            private recovery; it does not roll back the release or restore data.
          </p>
        )}
        {(reviewed.action === "pause" || reviewed.action === "cancel") && (
          <p>
            The current operator continues to its normal verification and acceptance or recovery.
            This decision stops new admissions; it does not interrupt a backup, reopen access or
            delete records.
          </p>
        )}
        {reviewed.window_start !== null && (
          <p>
            {time(reviewed.window_start)} through {time(reviewed.window_end)}
          </p>
        )}
        {(reviewed.sessions ?? []).map((item) => (
          <p key={item.instance}>
            {view.items.find((member) => member.instance === item.instance)?.name ?? item.instance}:{" "}
            {item.handling === "preserve" ? "Keep valid sessions" : "Require sign-in again"}
          </p>
        ))}
        {reviewed.expected_revision !== view.revision && (
          <p role="status">
            This batch changed. Return to review the latest status before obtaining a new
            credential. Your reviewed request has not been retried.
          </p>
        )}
        <Submission
          command={reviewed}
          title={
            reviewed.action === "start"
              ? "Start batch"
              : reviewed.action === "resume"
                ? "Resume batch"
                : reviewed.action === "pause"
                  ? "Pause after this operator"
                  : reviewed.action === "cancel"
                    ? "Cancel remaining operators"
                    : reviewed.action === "recheck"
                      ? "Check readiness again"
                      : "Skip this operator"
          }
          credentialRequired={reviewed.action !== "recheck"}
          disabled={reviewed.expected_revision !== view.revision}
        />
        <button
          onClick={() => {
            setReviewed(undefined);
            setConfirmed(false);
          }}
        >
          Back to review
        </button>
      </section>
    );
  if (
    ["completed", "mixed"].includes(view.state) ||
    (cancelled && !view.items.some((item) => item.can_skip))
  )
    return null;
  return (
    <section className="panel">
      <h2>{ready ? "Review batch" : "Queue controls"}</h2>
      <p>
        Operators are upgraded one at a time. Each stays paused until you accept its verified
        release. A failure stops the remaining queue.
      </p>
      {ready && (
        <>
          {view.items.map((item) => (
            <div key={item.instance}>
              <label htmlFor={`${id}-${item.sequence}`}>{item.name} — Session handling</label>
              <p>
                {item.original_release ?? "Not yet checked"} → {view.release} · Access at readiness:{" "}
                {item.access_active === null
                  ? "Unknown"
                  : item.access_active
                    ? "Enabled"
                    : "Disabled"}
              </p>
              <select
                id={`${id}-${item.sequence}`}
                value={handling[item.instance]}
                onChange={(event) =>
                  setHandling((prior) => ({
                    ...prior,
                    [item.instance]: event.target.value as "preserve" | "revoke",
                  }))
                }
              >
                <option value="preserve" disabled={!item.preserve_sessions}>
                  Keep valid sessions
                </option>
                <option value="revoke">Require sign-in again</option>
              </select>
            </div>
          ))}
          <label htmlFor={`${id}-start`}>Maintenance window starts (your local time)</label>
          <input
            id={`${id}-start`}
            type="datetime-local"
            step="60"
            value={start}
            onChange={(event) => setStart(event.target.value)}
          />
          <label htmlFor={`${id}-end`}>Maintenance window ends (your local time)</label>
          <input
            id={`${id}-end`}
            type="datetime-local"
            step="60"
            value={end}
            onChange={(event) => setEnd(event.target.value)}
          />
        </>
      )}
      <label htmlFor={`${id}-reason`}>Reason</label>
      <textarea
        id={`${id}-reason`}
        value={reason}
        maxLength={1000}
        onChange={(event) => setReason(event.target.value)}
      />
      <label htmlFor={`${id}-confirmed`}>
        <input
          id={`${id}-confirmed`}
          type="checkbox"
          checked={confirmed}
          onChange={(event) => setConfirmed(event.target.checked)}
        />
        I reviewed the selected operators, maintenance window and access consequences.
      </label>
      <div className="actions">
        {ready && (
          <button
            disabled={
              !confirmed || !reason.trim() || !start || !end || new Date(end) <= new Date(start)
            }
            onClick={() => review(hasRun ? "resume" : "start")}
          >
            {hasRun ? "Review and resume batch" : "Review batch"}
          </button>
        )}
        {["blocked", "paused", "ready"].includes(view.state) && (
          <button disabled={!reason.trim()} onClick={() => review("recheck")}>
            Check readiness again
          </button>
        )}
        {!cancelled && (
          <button
            disabled={!confirmed || !reason.trim() || view.state === "paused"}
            onClick={() => review("pause")}
          >
            Pause after this operator
          </button>
        )}
        {!cancelled && (
          <button disabled={!confirmed || !reason.trim()} onClick={() => review("cancel")}>
            Cancel remaining operators
          </button>
        )}
      </div>
      {view.items
        .filter((item) => item.can_skip)
        .map((item) => (
          <button
            key={item.instance}
            disabled={!confirmed || !reason.trim()}
            onClick={() => review("skip", item.instance)}
          >
            Skip {item.name}
          </button>
        ))}
    </section>
  );
}
const states: Record<string, string> = {
  checking: "Checking readiness",
  ready: "Ready for review",
  blocked: "Blocked",
  running: "In progress",
  paused: "Queue paused",
  cancelled: "Remaining upgrades canceled",
  completed: "Completed",
  mixed: "Finished with skipped or failed operators",
  queued: "Queued",
  checking_readiness: "Checking readiness",
  upgrading: "Upgrading",
  awaiting_acceptance: "Awaiting acceptance",
  accepted_restored: "Accepted — access restored",
  accepted_disabled: "Accepted — access disabled",
  containing: "Checking containment",
  skipped: "Skipped",
  rolled_back: "Rolled back",
  failed: "Needs recovery",
};
function remedy(code: string | null) {
  switch (code) {
    case "admin_batch_window_closed":
      return "The maintenance window closed. Check readiness again and review a new window before resuming.";
    case "admin_batch_child_recovery_required":
      return "Review the current operator's original upgrade. Complete acceptance, rollback or verified containment before resuming the queue.";
    case "admin_instance_operation_pending":
    case "admin_upgrade_already_running":
      return "Another operation owns this operator or the host upgrade slot. Finish or reconcile it, then check readiness again.";
    case "admin_batch_readiness_changed":
    case "admin_upgrade_inventory_changed":
      return "The operator changed since selection. Review its current state; if the selected revision changed, create a new batch for that operator.";
    case "admin_upgrade_schema_unsupported":
      return "The installed release cannot read this workspace format. Select a compatible, qualified release.";
    case "admin_upgrade_recovery_space_required":
      return "Private recovery staging has insufficient space. Resolve it privately, then check readiness again.";
    case "admin_upgrade_release_ineligible":
    case "admin_upgrade_capacity_unverified":
    case "admin_upgrade_qualification_changed":
      return "Refresh the private qualification and capacity evidence for this exact release, profile and host count, then check readiness again.";
    case "admin_upgrade_release_changed":
    case "admin_batch_target_changed":
      return "The installed artifact changed. Verify the qualified artifact privately and review a new batch; do not bypass the digest check.";
    case "admin_authority_fenced":
    case "admin_revoked":
    case "admin_restore_review_required":
      return "Administrator authority changed. Reconnect with current authority, reconcile the original operation and explicitly review the remaining queue.";
    case "admin_batch_containment_unverified":
    case "admin_batch_containment_pending":
      return "Containment is not verified. Leave access paused and review or retry the exact skip decision with fresh authorization.";
    default:
      return "A private administrator step is required. Review this operator's original operation, registered configuration, release qualification and recovery prerequisites, then check readiness again.";
  }
}
function ReadyDecisions({ view, disabled }: { view: View; disabled: boolean }) {
  const read = useRead<View>(`/admin-api/upgrade-batches/${view.id}/page/0/50`, 3000);
  const current = read.data;
  return (
    <>
      {read.failed && (
        <p role="status">The complete review is unavailable. Your queue has not been resumed.</p>
      )}
      {current && (
        <fieldset
          disabled={disabled || read.failed || read.expired || current.revision !== view.revision}
        >
          <legend>Batch decisions</legend>
          <BatchDecision key={current.id} view={current} />
        </fieldset>
      )}
    </>
  );
}
function BatchProgress({ id }: { id: string }) {
  const [offset, setOffset] = useState(0);
  const read = useRead<View>(`/admin-api/upgrade-batches/${id}/page/${offset}/10`, 3000);
  const view = read.data;
  if (!view)
    return (
      <p role="status">
        {read.expired
          ? "Sign in again to check the original batch. No work has been resubmitted."
          : read.failed
            ? "Batch status unavailable. Check the original submission; no work has been resubmitted."
            : "Loading batch…"}
      </p>
    );
  const accepted = (view.counts.accepted_restored ?? 0) + (view.counts.accepted_disabled ?? 0);
  return (
    <>
      <h1>Batch upgrade progress</h1>
      <a href="/upgrade-batches">View batch history</a>
      {read.failed && (
        <p role="status">
          Connection unavailable. Retained progress may be stale; decisions are disabled.
        </p>
      )}
      <p role="status">
        {states[view.state]} · {accepted} of {view.total} accepted · {view.release}
      </p>
      <progress aria-label="Accepted operator upgrades" max={view.total} value={accepted} />
      {!!view.counts.skipped && (
        <p>
          Skipped operators have not been accepted at the target release. A started operator may
          still be paused; review its original operation before returning it to service.
        </p>
      )}
      <p>
        Access restored: {view.counts.accepted_restored ?? 0} · Kept disabled:{" "}
        {view.counts.accepted_disabled ?? 0} · Skipped: {view.counts.skipped ?? 0} · Needs recovery:{" "}
        {(view.counts.failed ?? 0) + (view.counts.rolled_back ?? 0)}
      </p>
      {view.error && <p role="alert">{remedy(view.error)}</p>}
      {view.window_start !== null && (
        <p>
          Maintenance window: {time(view.window_start)} through {time(view.window_end)}
        </p>
      )}
      {view.items.map((item) => (
        <article className="item" key={item.instance}>
          <h2>
            <a href={`/operators/${item.instance}`}>{item.name}</a>
          </h2>
          <p>
            {states[item.status]} · {item.original_release ?? "Checking current release"} →{" "}
            {view.release}
          </p>
          <p>Readiness observed: {time(item.observed)}</p>
          <p>
            Access at readiness:{" "}
            {item.access_active === null ? "Unknown" : item.access_active ? "Enabled" : "Disabled"}.
            Acceptance still checks current authorization.
          </p>
          {item.error && (
            <p>
              {item.status === "skipped"
                ? "The earlier failure remains in this operator's history. Skipping did not reopen its access."
                : remedy(item.error)}
            </p>
          )}
          {item.operation && (
            <a className="button" href={`/operators/${item.instance}/upgrade/${item.operation}`}>
              {item.status === "awaiting_acceptance"
                ? "Review and accept this operator"
                : "View original upgrade"}
            </a>
          )}
          {item.rollback && (
            <a href={`/operators/${item.instance}/upgrade/${item.rollback}`}>
              View accepted rollback
            </a>
          )}
        </article>
      ))}
      <nav aria-label="Batch operator pages">
        <p>
          {offset + 1}–{Math.min(offset + view.items.length, view.total)} of {view.total} operators
        </p>
        <button disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 10))}>
          Previous operators
        </button>
        <button
          disabled={view.next_offset === null}
          onClick={() => setOffset(view.next_offset ?? offset)}
        >
          Next operators
        </button>
      </nav>
      {view.state === "ready" ? (
        <ReadyDecisions view={view} disabled={read.failed || read.expired} />
      ) : (
        <fieldset disabled={read.failed || read.expired}>
          <legend>Batch decisions</legend>
          <BatchDecision key={view.id} view={view} />
        </fieldset>
      )}
    </>
  );
}
function BatchHistory() {
  const [offset, setOffset] = useState(0);
  const read = useRead<Directory>(`/admin-api/upgrade-batches/page/${offset}`);
  return (
    <>
      <h1>Release upgrade batches</h1>
      <p>
        Admitted batches and their original outcomes remain here after reconnecting. Opening one
        never resubmits it.
      </p>
      {read.failed && (
        <p role="status">Batch history is unavailable. Retained results may be stale.</p>
      )}
      {read.data?.items.map((item) => (
        <article className="item" key={item.id}>
          <h2>
            <a href={`/upgrade-batches/${item.id}`}>{item.release}</a>
          </h2>
          <p>
            {states[item.state]} · {item.accepted} of {item.total} accepted · {item.skipped} skipped
          </p>
          <p>
            Created {time(item.created)} · Updated {time(item.updated)}
          </p>
        </article>
      ))}
      {read.data && !read.data.items.length && <p>No batches recorded.</p>}
      <nav aria-label="Batch history pages">
        <button disabled={!offset} onClick={() => setOffset(offset - 10)}>
          Previous batches
        </button>
        <button
          disabled={read.data?.next_offset == null}
          onClick={() => setOffset(read.data?.next_offset ?? offset)}
        >
          Next batches
        </button>
      </nav>
    </>
  );
}
export function BatchPage({ id }: { id?: string }) {
  return (
    <>
      <a className="back" href="/operators">
        ← Back to operators
      </a>
      {!id ? <BatchHistory /> : id === "new" ? <NewBatch /> : <BatchProgress id={id} />}
    </>
  );
}
