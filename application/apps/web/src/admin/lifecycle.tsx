import { useRef, useState, type FormEvent } from "react";
import { useRead, time, words } from "./reads";
import { browserTimeZone, TimeZoneSelect, ZonedDateTimeInput } from "../shared/zoned-date-time";
import type { components } from "../../../../packages/contracts/src/generated/admin-schema";

type Status = components["schemas"]["AccessStatus"];
type Report = components["schemas"]["RecoveryReport"];
type Command = components["schemas"]["CommandRequest"];
type Handoff = {
  id: string;
  expected_revision: number;
  state: string;
  report: Report | null;
  completion: string | null;
  private_command: string;
  binding?: components["schemas"]["RecoveryBinding"];
  acknowledged?: boolean;
};

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
        ? "Sign in again or obtain a fresh action credential. Your entries remain here."
        : "The change could not be confirmed. Check the original operation before retrying. Recovery, source or runtime checks may need private remediation.",
    );
  return (await response.json()) as T;
}

export function Lifecycle({
  instance,
  hostname,
  email,
  expires,
}: {
  instance: string;
  hostname: string;
  email: string;
  expires?: number;
}) {
  const source = useRead<Status>(`/admin-api/operators/${instance}/source-status`, 5000);
  const recovery = useRead<Handoff>(`/admin-api/operators/${instance}/recovery-handoff`, 5000);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const handoff = recovery.data;
  const status = source.data;
  const unavailable = source.failed || source.expired || !status;
  const verified = !!handoff && ["verified", "warning"].includes(handoff.state) && !!handoff.report;
  async function check(acknowledge = false) {
    if (!handoff || !status) return;
    setBusy(true);
    try {
      const value = await post<Handoff>(acknowledge ? "/recovery-acknowledge" : "/recovery-check", {
        recovery: { handoff_id: handoff.id, expected_revision: status.admin_revision },
      });
      setNotice(
        acknowledge
          ? "Recovery follow-up acknowledged. This does not verify recovery or enable access."
          : `Recovery: ${words(value.state)}. Access has not changed.`,
      );
    } catch (error) {
      setNotice((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel" aria-label="Access and onboarding controls">
      <h2>Access and onboarding</h2>
      {source.failed && (
        <p role="alert">
          Access status is unavailable. Use the private containment procedure if urgent disable
          cannot be confirmed.
        </p>
      )}
      {status?.identity_approved ? (
        <>
          <h3>Verify onboarding recovery</h3>
          <p>
            Private terminal work never asks for a passphrase here. Identity approval alone keeps
            business access blocked.
          </p>
          {handoff ? (
            <>
              <p>
                Recovery: <strong>{words(handoff.state)}</strong>
              </p>
              {handoff.binding && (
                <dl>
                  <dt>Instance / workspace</dt>
                  <dd>
                    {instance} · {handoff.binding.workspace_id}
                  </dd>
                  <dt>Approved binding revision</dt>
                  <dd>{handoff.binding.binding_revision}</dd>
                  <dt>Approved subject reference</dt>
                  <dd>{handoff.binding.subject}</dd>
                  <dt>Pinned configuration digest</dt>
                  <dd>{handoff.binding.configuration_digest}</dd>
                  <dt>Qualified release</dt>
                  <dd>{handoff.binding.release}</dd>
                </dl>
              )}
              {!verified && (
                <p>
                  Run the private verification command for this binding, then check verification.
                  Missing, failed, changed or overdue evidence cannot enable access.
                </p>
              )}
              <ol>
                <li>Create and validate an encrypted business archive.</li>
                <li>
                  Independently read it back from off-host storage and restore it in isolation.
                </li>
                <li>Publish and read back the current approved-binding reference.</li>
                <li>
                  Verify protected ingress, runtime isolation and qualified release acceptance.
                </li>
              </ol>
              <p>Run this fixed command in the private administrator terminal:</p>
              <pre>{handoff.private_command}</pre>
              {handoff.report && (
                <>
                  <p>
                    Last attempt: {time(handoff.report.observed)}. Recovery expires:{" "}
                    {time(handoff.report.expires)}. Snapshot:{" "}
                    {handoff.report.snapshot_marker ?? "Not verified"}.
                  </p>
                  <dl>
                    {(
                      ["archive", "readback", "restore", "approved_binding", "acceptance"] as const
                    ).map((check) => (
                      <div key={check}>
                        <dt>{words(check)}</dt>
                        <dd>
                          {handoff.report?.[check] ? "Verified" : "Not verified"} ·{" "}
                          {time(handoff.report?.completed?.[check])}
                        </dd>
                      </div>
                    ))}
                  </dl>
                </>
              )}
              <p>
                {handoff.acknowledged
                  ? "Recovery follow-up acknowledged; verification is still required."
                  : "Recovery follow-up has not been acknowledged."}
              </p>
              <div className="actions">
                <button disabled={busy || unavailable} onClick={() => void check()}>
                  Check verification
                </button>
                <button disabled={busy || unavailable} onClick={() => void check(true)}>
                  Acknowledge recovery follow-up
                </button>
              </div>
            </>
          ) : (
            <p role="status">
              Recovery checklist unavailable. Review the current approved binding privately.
            </p>
          )}
          {status.active && handoff?.completion && (
            <div>
              <h3>Onboarding complete</h3>
              <p>
                Access enabled. The operator must obtain a fresh eligible sign-in; no session is
                issued here.
              </p>
              <button
                onClick={() =>
                  void navigator.clipboard
                    .writeText(
                      `Your demo is ready. Return to https://${hostname}, sign in with ${email} if prompted, and select Continue to workspace. Access expires ${time(expires)}. Use synthetic data only.`,
                    )
                    .then(
                      () =>
                        setNotice("Ready-to-use instructions copied. Delivery is not confirmed."),
                      () =>
                        setNotice(
                          "Copy unavailable. Select and copy the ready-to-use instructions manually.",
                        ),
                    )
                }
              >
                Copy ready-to-use instructions
              </button>
            </div>
          )}
        </>
      ) : (
        <p>Approve the exact verified enrollment in operator setup before recovery verification.</p>
      )}
      {status && (
        <AccessForm
          key={instance}
          instance={instance}
          status={status}
          handoff={handoff}
          verified={verified && !recovery.failed}
          unavailable={unavailable}
        />
      )}
      <p role="status">{notice}</p>
    </section>
  );
}

function AccessForm({
  instance,
  status,
  handoff,
  verified,
  unavailable,
}: {
  instance: string;
  status: Status;
  handoff?: Handoff;
  verified: boolean;
  unavailable: boolean;
}) {
  const [action, setAction] = useState<Command["action"]>("disable");
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [credential, setCredential] = useState("");
  const [starts, setStarts] = useState("");
  const [ends, setEnds] = useState("");
  const [zone, setZone] = useState(browserTimeZone);
  const [id, setId] = useState(crypto.randomUUID());
  const [authorized, setAuthorized] = useState(false);
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [notice, setNotice] = useState("");
  const result = useRef<HTMLParagraphElement>(null);
  // Polling must not erase the original attempt or silently rebase a reviewed
  // action onto a newer source revision. A conflict requires explicit review.
  const [reviewed] = useState(status);
  const command: Command = {
    subject: null,
    enrollment_received_at: null,
    replacement_email: null,
    starts: null,
    expires: null,
    evidence_id: null,
    acceptance_id: null,
    operation_id: id,
    instance,
    action,
    reason,
    confirmed: true,
    expected_revision: reviewed.admin_revision,
    expected_binding_revision: reviewed.binding_revision,
    fence: reviewed.admin_fence,
    ...(action === "renew"
      ? { starts: new Date(starts).getTime() / 1000, expires: new Date(ends).getTime() / 1000 }
      : {}),
    ...(["enable", "complete_onboarding"].includes(action)
      ? { evidence_id: handoff?.report?.id, acceptance_id: handoff?.report?.id }
      : {}),
  };
  const needsGrant = !["disable", "revoke"].includes(action);
  const invalid =
    unavailable ||
    !reason.trim() ||
    !confirmed ||
    (action === "renew" && (!starts || !ends)) ||
    (["enable", "complete_onboarding"].includes(action) && (!verified || status.active)) ||
    (action === "enable" && !handoff?.completion);
  function edit() {
    setAuthorized(false);
    setCredential("");
    setId(crypto.randomUUID());
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (invalid || busy) return;
    setBusy(true);
    try {
      if (needsGrant && !authorized) {
        await post("/reauthenticate", { credential, command });
        setCredential("");
        setAuthorized(true);
        setNotice("Action authorized. Review the consequence, then confirm the change.");
      } else {
        setSent(true);
        await post("/commands", { command });
        setNotice(
          action === "renew"
            ? "New demo window recorded. Access remains blocked until recovery verification and explicit onboarding completion. Fresh sign-in is required."
            : action === "disable"
              ? "App access disabled and sessions revoked. Private Cloudflare allowance and session revocation still requires independent verification; this receipt does not confirm edge denial."
              : "Access change recorded. Review the current status before another change.",
        );
      }
    } catch (error) {
      setNotice((error as Error).message);
    } finally {
      setBusy(false);
      requestAnimationFrame(() => result.current?.focus());
    }
  }
  return (
    <form onSubmit={(event) => void submit(event)}>
      <h3>Maintain access</h3>
      <fieldset disabled={busy || sent}>
        <label>
          Action
          <select
            value={action}
            onChange={(event) => {
              setAction(event.target.value as Command["action"]);
              edit();
            }}
          >
            <option value="disable">Disable access</option>
            <option value="revoke">Revoke all sessions</option>
            {handoff?.completion ? (
              <option value="enable" disabled={!verified || status.active}>
                Enable access
              </option>
            ) : (
              <option value="complete_onboarding" disabled={!verified || status.active}>
                Complete onboarding and enable access
              </option>
            )}
            <option value="renew">Extend demo</option>
          </select>
        </label>
        <p>
          {action === "disable"
            ? "Immediately fences access and revokes sessions. Records and recovery points are retained."
            : action === "revoke"
              ? "Revokes current sessions and requires fresh identity proof; retains the assignment."
              : action === "renew"
                ? "Fences and stops only this operator, publishes a new window of at most fourteen days, restarts with existing data and leaves access blocked."
                : "Enables only the currently approved identity after current recovery and acceptance checks. The operator must sign in again."}
        </p>
        {action === "renew" && (
          <>
            <TimeZoneSelect
              label="Demo time zone"
              value={zone}
              onChange={(next) => {
                setZone(next);
                edit();
              }}
            />
            <ZonedDateTimeInput
              label="New window starts"
              required
              value={starts}
              timeZone={zone}
              onChange={(value) => {
                setStarts(value);
                edit();
              }}
            />
            <ZonedDateTimeInput
              label="New window expires"
              required
              value={ends}
              timeZone={zone}
              onChange={(value) => {
                setEnds(value);
                edit();
              }}
            />
            {starts && (
              <p>
                New start: {time(new Date(starts).getTime() / 1000)}. Review any gap or overlap with
                the current window before confirming.
              </p>
            )}
          </>
        )}
        <label>
          Reason
          <textarea
            required
            maxLength={1000}
            value={reason}
            onChange={(event) => {
              setReason(event.target.value);
              edit();
            }}
          />
        </label>
        <label>
          <input
            type="checkbox"
            checked={confirmed}
            onChange={(event) => {
              setConfirmed(event.target.checked);
              edit();
            }}
          />
          I reviewed this operator and the consequence
        </label>
        {needsGrant && (
          <>
            <p>
              Obtain a one-use action credential from the private launcher for exactly this command:
            </p>
            <pre>{JSON.stringify(command, null, 2)}</pre>
            <label>
              One-use action credential
              <input
                type="password"
                autoComplete="off"
                value={credential}
                onChange={(event) => setCredential(event.target.value)}
              />
            </label>
          </>
        )}
        <div className="actions">
          <button type="submit" disabled={invalid || (needsGrant && !authorized && !credential)}>
            {needsGrant && !authorized ? "Authorize reviewed change" : "Confirm access change"}
          </button>
        </div>
      </fieldset>
      <p role="status" tabIndex={-1} ref={result}>
        {notice}
      </p>
      {sent && (
        <p>
          <a href={`/operations/${id}`}>Check original operation</a> ·{" "}
          <a href={window.location.pathname}>Review current status</a>
        </p>
      )}
      <details>
        <summary>Change sign-in email — private assistance</summary>
        <p>
          Disable access first. In the private terminal, stage an exact replacement Access policy,
          then submit a reviewed replace_email command with the new email using the same
          action-bound authorization and operation lookup. Existing sessions are revoked, the old
          subject is removed, and access stays blocked. Receive the new verified enrollment, approve
          it, refresh recovery and explicitly complete onboarding. A typed email alone never
          activates access.
        </p>
      </details>
    </form>
  );
}
