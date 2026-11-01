import { useState, type FormEvent } from "react";
import { useRead, time, words, type Operator } from "./reads";
import type { components } from "../../../../packages/contracts/src/generated/admin-schema";

type Command = components["schemas"]["UpgradeCommand"];
type BatchCommand = components["schemas"]["BatchCommand"];
type View = components["schemas"]["UpgradeView"];
type Release = components["schemas"]["InstalledRelease"];
type Receipt = { id: string; state: string; revision: number };
const route = (instance: string, id: string) => `/operators/${instance}/upgrade/${id}`;

async function post<T>(path: string, body: object): Promise<T> {
  const csrf = document.querySelector<HTMLInputElement>('header input[name="csrf"]')?.value ?? "";
  const response = await fetch(path, {
    method: "POST",
    credentials: "same-origin",
    cache: "no-store",
    headers: { "Content-Type": "application/json", "X-Epm-Admin-Csrf": csrf },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(10000),
  });
  if (!response.ok)
    throw new Error(
      response.status === 401 || response.status === 403
        ? "Sign in again or obtain a fresh action-bound credential. Your reviewed request is retained on this page."
        : "The request could not be confirmed. Check the original submission before retrying.",
    );
  return (await response.json()) as T;
}

export function Submission({
  command,
  title,
  credentialRequired = true,
  onDispatch,
  disabled = false,
}: {
  command: Command | BatchCommand;
  title: string;
  credentialRequired?: boolean;
  onDispatch?: () => void;
  disabled?: boolean;
}) {
  const isBatch = "members" in command;
  const destination = (id: string) =>
    isBatch ? `/upgrade-batches/${id}` : route((command as Command).instance, id);
  const [credential, setCredential] = useState("");
  const [busy, setBusy] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const [notice, setNotice] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    onDispatch?.();
    setBusy(true);
    setNotice("");
    // The URL retains the original key before dispatch, including a lost response.
    window.history.replaceState(null, "", destination(command.id));
    try {
      const result = await post<Receipt>(isBatch ? "/upgrade-batch-command" : "/upgrade-command", {
        [isBatch ? "batch" : "upgrade"]: command,
        credential,
      });
      window.location.assign(destination(result.id));
    } catch (cause) {
      setUncertain(true);
      setNotice(cause instanceof Error ? cause.message : "Check the original submission.");
    } finally {
      setBusy(false);
      setCredential("");
    }
  }
  async function check() {
    setBusy(true);
    try {
      const response = await fetch(
        `/admin-api/${isBatch ? "upgrade-batch-commands" : "upgrade-commands"}/${command.id}`,
        {
          credentials: "same-origin",
          cache: "no-store",
        },
      );
      if (!response.ok) throw new Error("Sign in again or check the private connection.");
      const result = (await response.json()) as {
        found: boolean;
        operation?: View | null;
        batch?: { id: string } | null;
      };
      const original = isBatch ? result.batch?.id : result.operation?.operation.id;
      if (original) window.location.assign(destination(original));
      else {
        setUncertain(false);
        setNotice("No submission is recorded yet. You can retry this same reviewed request.");
      }
    } catch (cause) {
      setNotice(
        cause instanceof Error ? cause.message : "The original submission could not be checked.",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <form onSubmit={(event) => void submit(event)} aria-label={title}>
      {credentialRequired && (
        <>
          <details>
            <summary>Obtain an action credential privately</summary>
            <p>
              Send this exact request to the private launcher’s{" "}
              {isBatch ? "batch-grant" : "upgrade-grant"} operation. The credential authorizes only
              this reviewed decision.
            </p>
            <pre>
              {JSON.stringify(
                {
                  action: isBatch ? "batch-grant" : "upgrade-grant",
                  [isBatch ? "batch" : "upgrade"]: command,
                },
                null,
                2,
              )}
            </pre>
          </details>
          <label>
            Action credential
            <input
              type="password"
              autoComplete="off"
              value={credential}
              onChange={(event) => setCredential(event.target.value)}
              disabled={disabled || busy || uncertain}
              required
            />
          </label>
        </>
      )}
      {notice && <p role="alert">{notice}</p>}
      <div className="actions">
        <button disabled={disabled || busy || uncertain || (credentialRequired && !credential)}>
          {busy ? "Checking…" : title}
        </button>
        {uncertain && (
          <button type="button" disabled={busy} onClick={() => void check()}>
            Check original submission
          </button>
        )}
      </div>
    </form>
  );
}

function Decisions({ view, instance }: { view: View; instance: string }) {
  const operation = view.operation;
  const [mode, setMode] = useState<Command["action"]>(
    operation.kind === "upgrade_check" ? "start" : "accept",
  );
  const [sessions, setSessions] = useState<"preserve" | "revoke">(
    view.target?.preserve_sessions ? "preserve" : "revoke",
  );
  const [restore, setRestore] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [reviewed, setReviewed] = useState<Command>();
  const waitForAcceptance =
    ["waiting", "unknown", "failed"].includes(operation.state) &&
    operation.steps.find((step) => step.state !== "verified")?.kind === "accept";
  const canStart = operation.kind === "upgrade_check" && operation.state === "succeeded";
  const paused = operation.steps.some((step) => step.kind === "pause" && step.state === "verified");
  const canRollback =
    operation.kind === "upgrade" &&
    paused &&
    ["waiting", "failed", "unknown", "paused"].includes(operation.state) &&
    !operation.cancel_requested;
  if (reviewed)
    return (
      <section className="panel" aria-label="Reviewed upgrade decision">
        <h2>{mode === "start" ? "Confirm the interruption" : "Confirm your decision"}</h2>
        <p>
          {view.original_release} → {view.target?.release}
        </p>
        <p>
          Access remains subject to the current identity, enrollment window and any later
          disablement. A failed upgrade can leave access paused until recovery completes.
        </p>
        <Submission
          command={reviewed}
          title={
            mode === "start"
              ? "Start upgrade"
              : mode === "rollback"
                ? "Roll back"
                : restore
                  ? view.batch
                    ? "Accept and continue"
                    : "Accept upgrade and restore access"
                  : view.batch
                    ? "Accept with access disabled and continue"
                    : "Accept upgrade and keep access disabled"
          }
        />
        <button
          onClick={() => {
            setReviewed(undefined);
            setConfirmed(false);
          }}
        >
          Back
        </button>
      </section>
    );
  if (!canStart && !waitForAcceptance && !canRollback) return null;
  return (
    <section className="panel" aria-label="Upgrade decision">
      <h2>{canStart ? "Prepare the interruption" : "Review the result"}</h2>
      {canStart ? (
        <>
          <p>
            Access will pause while the upgrade runs. Ask the operator to save unfinished work
            before continuing. Valid sessions can remain signed in; open tabs must reload before
            continuing.
          </p>
          <label>
            Session handling
            <select
              value={sessions}
              onChange={(event) => setSessions(event.target.value as "preserve" | "revoke")}
            >
              <option value="preserve" disabled={!view.target?.preserve_sessions}>
                Keep valid sessions
              </option>
              <option value="revoke">Require sign-in again</option>
            </select>
          </label>
          {!view.target?.preserve_sessions && (
            <p>This release requires sign-in again; session preservation is not qualified.</p>
          )}
        </>
      ) : (
        <>
          {waitForAcceptance && (
            <p>
              The selected release is running. Verification passed. Operator access remains paused.
            </p>
          )}
          <label>
            Decision
            <select
              value={mode}
              onChange={(event) => setMode(event.target.value as Command["action"])}
            >
              <option value="accept" disabled={!waitForAcceptance}>
                Accept the verified release
              </option>
              <option value="rollback" disabled={!canRollback}>
                Roll back to the previous release
              </option>
            </select>
          </label>
          {mode === "accept" && (
            <label>
              <input
                type="checkbox"
                checked={restore}
                onChange={(event) => setRestore(event.target.checked)}
              />
              Restore access if the original authorization is still valid
            </label>
          )}
          <p>
            Rollback validates the previous release against the current workspace. It never silently
            restores an older backup.
          </p>
        </>
      )}
      <label>
        <input
          type="checkbox"
          checked={confirmed}
          onChange={(event) => setConfirmed(event.target.checked)}
        />
        {canStart
          ? "I agreed a maintenance window and reviewed the interruption."
          : "I reviewed the current result and access consequences."}
      </label>
      <button
        disabled={!confirmed || (mode === "accept" && !waitForAcceptance)}
        onClick={() =>
          setReviewed({
            release: null,
            session_handling: canStart ? sessions : null,
            restore_access: mode === "accept" ? restore : null,
            id: crypto.randomUUID(),
            action: mode,
            instance,
            operation: operation.id,
            expected_revision: operation.revision,
            reason: canStart
              ? "Agreed operator release upgrade"
              : "Reviewed operator upgrade decision",
            confirmed: true,
          })
        }
      >
        Review decision
      </button>
    </section>
  );
}

function Operation({ instance, id }: { instance: string; id: string }) {
  const read = useRead<View>(`/admin-api/upgrades/${id}`, 3000);
  const [credential, setCredential] = useState("");
  const [message, setMessage] = useState("");
  const view = read.data;
  if (!view)
    return (
      <section className="panel">
        <h2>Checking the original operation</h2>
        <p role="status">
          {read.expired
            ? "Sign in again. No operation has been resubmitted."
            : read.failed
              ? "The original operation is unavailable or not yet recorded. Refresh this page or find it in Operations before retrying."
              : "Loading…"}
        </p>
        <a href="/operations">View operations</a>
      </section>
    );
  const operation = view.operation;
  const verified = operation.steps.filter((step) => step.state === "verified").length;
  const resumable =
    ["unknown", "failed", "paused"].includes(operation.state) && !operation.cancel_requested;
  const cancelable =
    operation.kind !== "upgrade_rollback" &&
    !operation.steps.some((step) => step.kind === "pause" && step.state !== "pending") &&
    !["succeeded", "cancelled"].includes(operation.state);
  async function control(action: "resume" | "cancel") {
    try {
      await post(`/${action}`, {
        operation_id: id,
        expected_revision: operation.revision,
        ...(action === "resume" ? { credential } : {}),
      });
      setMessage(
        action === "resume"
          ? "Resume requested for this original operation."
          : "Cancellation requested before access was paused.",
      );
    } catch (cause) {
      setMessage(cause instanceof Error ? cause.message : "Check the operation before retrying.");
    } finally {
      setCredential("");
    }
  }
  return (
    <>
      <section className="panel" aria-label="Upgrade progress">
        {view.batch && (
          <a className="back" href={`/upgrade-batches/${view.batch}`}>
            ← Back to batch upgrade progress
          </a>
        )}
        <h2>Upgrade progress</h2>
        {read.failed && (
          <p role="status">The connection is unavailable; this progress may be stale.</p>
        )}
        <p role="status">
          {words(operation.state)} · {verified} of {operation.steps.length} checkpoints verified
        </p>
        <progress
          aria-label="Verified upgrade checkpoints"
          max={operation.steps.length}
          value={verified}
        />
        <p>
          {view.original_release ?? "Current release"} → {view.target?.release ?? "Checking target"}
        </p>
        {view.workspace_id && <p>Workspace reference: {view.workspace_id}</p>}
        <ol>
          {operation.steps.map((step) => (
            <li key={step.sequence}>
              {words(step.kind)} — {words(step.state)}
            </li>
          ))}
        </ol>
        {operation.error && (
          <p role="alert">
            Private administrator step required. Check recovery credentials, capacity, release
            compatibility and the operation details. Access remains paused after the pause
            checkpoint.
          </p>
        )}
        {(view.evidence ?? []).map((proof) => (
          <p key={proof.id}>
            {words(proof.stage)} verification: {words(proof.state)} · {time(proof.observed)}
          </p>
        ))}
        <p>
          <a href={`/operations/${operation.id}`}>View operation details</a>
        </p>
        {operation.state === "succeeded" && operation.kind !== "upgrade_check" && (
          <p>
            Release acceptance completed. Operator sign-in verification is a separate check; no
            session was issued by this operation.
          </p>
        )}
        {view.batch && operation.state === "succeeded" && (
          <a className="button" href={`/upgrade-batches/${view.batch}`}>
            Return to batch progress
          </a>
        )}
        {message && <p role="status">{message}</p>}
        {resumable && (
          <>
            <p>
              Obtain a resume-grant credential for this operation and its current revision through
              the private launcher.
            </p>
            <label>
              Resume credential
              <input
                type="password"
                autoComplete="off"
                value={credential}
                onChange={(event) => setCredential(event.target.value)}
              />
            </label>
            <button disabled={!credential} onClick={() => void control("resume")}>
              Resume upgrade
            </button>
          </>
        )}
        {cancelable && (
          <button onClick={() => void control("cancel")}>Cancel before interruption</button>
        )}
      </section>
      <Decisions key={`${operation.id}:${operation.state}`} instance={instance} view={view} />
    </>
  );
}

type UpgradeOperator = Operator & { registered_revision: number };
function UpgradeChooser({ instance, item }: { instance: string; item?: UpgradeOperator }) {
  const options = useRead<{ items: Release[] }>(`/admin-api/operators/${instance}/upgrade-options`);
  const [release, setRelease] = useState("");
  const [check, setCheck] = useState<Command>();
  const [locked, setLocked] = useState(false);
  return (
    <section className="panel" aria-label="Choose installed release">
      <h2>Choose an installed release</h2>
      <p>
        Only installed, compatible releases qualified for this operator profile can be selected.
        Installing release artifacts remains private administration.
      </p>
      {options.failed && (
        <p role="alert">
          Release choices could not be verified. Check the private installation and qualification
          reports.
        </p>
      )}
      <label>
        Target release
        <select
          value={release}
          disabled={locked || options.failed || !item}
          onChange={(event) => {
            const next = event.target.value;
            setRelease(next);
            setCheck(
              next && item
                ? {
                    id: crypto.randomUUID(),
                    instance,
                    action: "check",
                    expected_revision: item.registered_revision,
                    release: next,
                    operation: null,
                    session_handling: null,
                    restore_access: null,
                    confirmed: false,
                    reason: "Review installed-release readiness",
                  }
                : undefined,
            );
          }}
        >
          <option value="">Choose a release…</option>
          {options.data?.items.map((target) => (
            <option key={target.release} value={target.release} disabled={!target.eligible}>
              {target.release}
              {target.eligible ? "" : " — Unavailable"}
            </option>
          ))}
        </select>
      </label>
      {options.data?.items.map((target) => (
        <article key={target.release}>
          <h3>{target.release}</h3>
          <p>Installed {time(target.installed)}</p>
          <p>{target.notes}</p>
          {target.blockers.map((reason) => (
            <p key={reason}>{reason}</p>
          ))}
        </article>
      ))}
      {check ? (
        <Submission
          key={check.id}
          command={check}
          title="Check readiness"
          credentialRequired={false}
          onDispatch={() => setLocked(true)}
        />
      ) : (
        <button disabled>Check readiness</button>
      )}
      <a href={`/operators/${instance}`}>Cancel</a>
    </section>
  );
}
export function UpgradePage({ instance, id }: { instance: string; id?: string }) {
  const record = useRead<{ items: UpgradeOperator[] }>(`/admin-api/operators/${instance}`);
  const item = record.data?.items[0];
  return (
    <>
      <a className="back" href={`/operators/${instance}`}>
        ← Back to {item?.name ?? "operator"}
      </a>
      <h1>Upgrade operator</h1>
      {item && (
        <p>
          {item.name} · {item.email} · Current release: {item.release}
        </p>
      )}
      {id ? (
        <Operation instance={instance} id={id} />
      ) : (
        <UpgradeChooser instance={instance} item={item} />
      )}
    </>
  );
}
