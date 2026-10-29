import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react";
import { useRead, time, words } from "./reads";
import { TimeZoneSelect, ZonedDateTimeInput, browserTimeZone } from "../shared/zoned-date-time";

import type { components } from "../../../../packages/contracts/src/generated/admin-schema";
type SetupData = Required<components["schemas"]["SetupData"]>;
type Options = components["schemas"]["SetupOptions"];
type Setup = Omit<components["schemas"]["SetupView"], "data"> & { data: SetupData };

function message(code: string) {
  const messages: Record<string, string> = {
    admin_operator_email_exists:
      "This email already has an operator. Open the existing operator instead.",
    admin_capacity_unqualified:
      "The qualified operator ceiling has been reached. Save this setup and review Qualification plan.",
    admin_physical_capacity_blocked:
      "Memory or disk reservations do not fit. Save this setup and review host capacity privately.",
    admin_setup_revision_conflict:
      "This setup changed elsewhere. Your entries are still here; review the latest saved setup before continuing.",
    admin_provider_seats_unavailable:
      "Available Access seats have not been verified. Save this setup and check the provider account privately.",
    admin_reauthentication_required:
      "Obtain a fresh action-bound credential from the private launcher.",
    admin_setup_incomplete:
      "Complete the operator, release and demo window before creating resources.",
  };
  return (
    messages[code] ??
    "The request could not be completed. Keep this page open and check its original saved setup or operation before retrying."
  );
}

async function post<T>(path: string, body: object): Promise<T> {
  const csrf = document.querySelector<HTMLInputElement>('header input[name="csrf"]')?.value ?? "";
  let response: Response;
  let result: { detail?: { code?: string } };
  try {
    response = await fetch(path, {
      method: "POST",
      credentials: "same-origin",
      cache: "no-store",
      headers: { "Content-Type": "application/json", "X-Epm-Admin-Csrf": csrf },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(10000),
    });
    result = (await response.json()) as { detail?: { code?: string } };
  } catch {
    throw new Error(
      "The response could not be confirmed. Check the original saved setup or operation before retrying.",
    );
  }
  if (!response.ok) {
    if (response.status === 401 || response.status === 403)
      throw new Error(
        "Your authority needs checking. Sign in again or obtain the required action credential. Admitted work continues.",
      );
    throw new Error(message(result.detail?.code ?? ""));
  }
  return result as T;
}

export function SetupPage({ id }: { id?: string }) {
  const options = useRead<Options>("/admin-api/setup-options");
  const read = useRead<Setup | { items: Setup[] }>(
    id && id !== "new" ? `/admin-api/setup-drafts/${id}` : "/admin-api/setup-drafts",
  );
  if ((options.failed || read.failed) && (!options.data || !read.data))
    return (
      <p role="alert">
        Setup is unavailable. Your acknowledged drafts remain saved; reload to check them.
      </p>
    );
  if (!options.data || !read.data) return <p role="status">Loading setup…</p>;
  const unavailable = options.expired || read.expired;
  const warning =
    options.failed || read.failed ? (
      <p role="alert">
        {unavailable ? (
          <>
            Your session ended. Your entries remain on this page. Save requires signing in again.{" "}
            <a href={window.location.pathname}>Sign in</a>
          </>
        ) : (
          "Connection unavailable. Your entries remain on this page; acknowledged setup is still saved."
        )}
      </p>
    ) : null;
  if (!id)
    return (
      <>
        <h1>Saved operator setups</h1>
        <a className="button" href="/setups/new">
          Add operator
        </a>
        {"items" in read.data &&
          read.data.items.map((item) => (
            <article className="panel" key={item.id}>
              <h2>
                <a href={`/setups/${item.id}`}>{item.data.name || "Unnamed operator"}</a>
              </h2>
              <p>
                {words(item.state)} · Saved {time(item.saved)}
              </p>
            </article>
          ))}
      </>
    );
  if ("items" in read.data)
    return (
      <>
        {warning}
        <SetupForm options={options.data} unavailable={unavailable} />
      </>
    );
  if (read.data.state === "discarded")
    return (
      <>
        <a className="back" href="/setups">
          ← Back to Saved setups
        </a>
        <h1>Setup discarded</h1>
        <p>No provisioning resources were created. Start a new setup to continue.</p>
      </>
    );
  return read.data.state === "started" ? (
    <SetupProgress initial={read.data} />
  ) : (
    <>
      {warning}
      <SetupForm initial={read.data} options={options.data} unavailable={unavailable} />
    </>
  );
}

function SetupForm({
  initial,
  options,
  unavailable,
}: {
  initial?: Setup;
  options: Options;
  unavailable: boolean;
}) {
  const [id] = useState(initial?.id ?? crypto.randomUUID());
  const [draft, setDraft] = useState(initial);
  const [data, setData] = useState<SetupData>(
    () =>
      initial?.data ?? {
        name: "",
        email: "",
        reference: "",
        support: "",
        release: options.releases[0] ?? "",
        template: "synthetic",
        access: "read_write",
        starts: Math.floor(Date.now() / 60000) * 60,
        expires: Math.floor(Date.now() / 60000) * 60 + 14 * 86400,
        timezone: browserTimeZone(),
      },
  );
  const [step, setStep] = useState(0),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const [confirmed, setConfirmed] = useState(false),
    [creating, setCreating] = useState(false);
  const leaving = useRef(false);
  const [operationId] = useState(crypto.randomUUID());
  const [review, setReview] = useState<Setup>();
  const heading = useRef<HTMLHeadingElement>(null),
    alert = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (error) alert.current?.focus();
  }, [error]);
  const dirty = JSON.stringify(data) !== JSON.stringify(draft?.data);
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if (dirty && !creating && !leaving.current) event.preventDefault();
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty, creating]);
  const edit = <K extends keyof SetupData>(key: K, value: SetupData[K]) => {
    setData({ ...data, [key]: value });
    setError("");
    setConfirmed(false);
    setReview(undefined);
  };
  const save = async () => {
    const result = await post<Setup>("/setup-command", {
      setup: { action: "save", draft_id: id, expected_revision: draft?.revision ?? 0, data },
    });
    setDraft(result);
    window.history.replaceState(null, "", `/setups/${id}`);
    return result;
  };
  const attempt = async (action: () => Promise<void>) => {
    if (unavailable) {
      setError("Sign in again before saving or creating resources. Your entries are still here.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (failure) {
      setError(
        failure instanceof Error
          ? failure.message
          : "Saving could not be confirmed. Check the saved setup.",
      );
    } finally {
      setBusy(false);
    }
  };
  const proceed = () =>
    attempt(async () => {
      await save();
      setStep(step + 1);
      setTimeout(() => heading.current?.focus(), 0);
    });
  return (
    <>
      <a className="back" href="/setups">
        ← Back to Saved setups
      </a>
      <section className="panel setup-form">
        <h1 ref={heading} tabIndex={-1}>
          Add operator — {["Operator", "Demo", "Review"][step]}
        </h1>
        <ol className="setup-steps" aria-label="Setup progress">
          {["Operator", "Demo", "Review"].map((name, index) => (
            <li key={name} aria-current={step === index ? "step" : undefined}>
              {index + 1}. {name}
            </li>
          ))}
        </ol>
        <p>
          Save a setup even while capacity is unresolved. No resources or invitations are created
          until you confirm the review.
        </p>
        {error && (
          <div ref={alert} tabIndex={-1} role="alert">
            {error} <a href={`/setups/${id}`}>Check saved setup</a>
          </div>
        )}
        <form
          method="post"
          action="/setup-command"
          onSubmit={(event) => {
            event.preventDefault();
            if (step < 2) void proceed();
            else
              void attempt(async () => {
                if (!confirmed) return;
                if (!review?.review_hash)
                  throw new Error("Wait for the assigned demo address before confirming creation.");
                const saved = dirty ? await save() : draft;
                if (!saved) return;
                await post<Setup>("/setup-command", {
                  setup: {
                    action: "create",
                    draft_id: id,
                    expected_revision: saved.revision,
                    operation_id: operationId,
                    confirmed: true,
                    review_hash: review.review_hash,
                  },
                });
                leaving.current = true;
                setCreating(true);
                window.location.assign(`/setups/${id}`);
              });
          }}
        >
          <fieldset disabled={busy}>
            <legend>{["Operator details", "Demo settings", "Confirm isolated demo"][step]}</legend>
            {step === 0 && (
              <>
                {(
                  [
                    ["name", "Display name", "text"],
                    ["email", "Exact sign-in email", "email"],
                    ["support", "Support email", "email"],
                    ["reference", "Reference code (optional)", "text"],
                  ] as const
                ).map(([key, title, type]) => (
                  <label key={key}>
                    {title}
                    <input
                      name={key}
                      type={type}
                      required={key !== "reference"}
                      maxLength={key === "name" ? 100 : key === "reference" ? 80 : 254}
                      value={data[key]}
                      autoCapitalize={type === "email" ? "none" : undefined}
                      onChange={(e) => edit(key, e.target.value)}
                    />
                  </label>
                ))}
                <p>
                  The reference code is a label, not a password. Use the operator’s exact approved
                  email; each operator has an isolated portfolio.
                </p>
              </>
            )}
            {step === 1 && (
              <>
                <label>
                  Installed qualified release
                  <select
                    name="release"
                    value={data.release}
                    required
                    onChange={(e) => edit("release", e.target.value)}
                  >
                    <option value="">Select an installed release</option>
                    {options.releases.map((release) => (
                      <option key={release}>{release}</option>
                    ))}
                  </select>
                </label>
                <fieldset>
                  <legend>Fresh portfolio</legend>
                  {(
                    [
                      ["synthetic", "Synthetic portfolio"],
                      ["empty", "Empty synthetic workspace"],
                    ] as const
                  ).map(([value, title]) => (
                    <label key={value}>
                      <input
                        type="radio"
                        name="template"
                        checked={data.template === value}
                        onChange={() => edit("template", value)}
                      />
                      {title}
                    </label>
                  ))}
                </fieldset>
                <fieldset>
                  <legend>Access profile</legend>
                  {(
                    [
                      ["read_write", "Read and write"],
                      ["read_only", "Read only"],
                    ] as const
                  ).map(([value, title]) => (
                    <label key={value}>
                      <input
                        type="radio"
                        name="access"
                        checked={data.access === value}
                        onChange={() => edit("access", value)}
                      />
                      {title}
                    </label>
                  ))}
                </fieldset>
                <TimeZoneSelect value={data.timezone} onChange={(zone) => edit("timezone", zone)} />
                <ZonedDateTimeInput
                  label="Starts"
                  value={new Date(data.starts * 1000).toISOString()}
                  timeZone={data.timezone}
                  required
                  onChange={(value) => edit("starts", value ? Date.parse(value) / 1000 : 0)}
                />
                <ZonedDateTimeInput
                  label="Expires"
                  value={new Date(data.expires * 1000).toISOString()}
                  timeZone={data.timezone}
                  required
                  onChange={(value) => edit("expires", value ? Date.parse(value) / 1000 : 0)}
                />
                <p>
                  Maximum fourteen days. Workspace limit {options.workspace_mib} MiB; individual
                  file limit {options.file_mib} MiB. {options.backup_policy}
                </p>
              </>
            )}
            {step === 2 && (
              <>
                <ReviewAssignment id={id} review={review} onRead={setReview} />
                <dl>
                  <dt>Operator</dt>
                  <dd>
                    {data.name} · {data.email}
                  </dd>
                  <dt>Support</dt>
                  <dd>{data.support}</dd>
                  <dt>Portfolio</dt>
                  <dd>
                    {words(data.template)} · {words(data.access)} · {data.release}
                  </dd>
                  <dt>Window</dt>
                  <dd>
                    {time(data.starts)} through {time(data.expires)}
                  </dd>
                  <dt>Reservations</dt>
                  <dd>
                    Unique hostname, port, Unix identity, workspace and storage are assigned by the
                    server. Admission rechecks qualified capacity, Access seats and retained
                    resources.
                  </dd>
                </dl>
                <p>
                  Creation does not enable access. Manual provider verification, exact enrollment
                  approval and independent recovery completion are separate gates. Existing
                  operators are not restarted.
                </p>
                <label>
                  <input
                    type="checkbox"
                    name="confirmed"
                    checked={confirmed}
                    onChange={(e) => setConfirmed(e.target.checked)}
                    required
                  />
                  I reviewed the recipient, dates, isolation and resource limits.
                </label>
              </>
            )}
          </fieldset>
          <div className="actions">
            {step > 0 && (
              <button
                type="button"
                disabled={busy}
                onClick={() => {
                  setStep(step - 1);
                  heading.current?.focus();
                }}
              >
                Previous
              </button>
            )}
            <button type="submit" disabled={busy}>
              {busy ? "Saving…" : step === 2 ? "Create isolated demo" : "Save and continue"}
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() =>
                void attempt(async () => {
                  await save();
                  leaving.current = true;
                  setCreating(true);
                  window.location.assign("/setups");
                })
              }
            >
              Save and close
            </button>
            {draft && (
              <button
                type="button"
                disabled={busy}
                onClick={() =>
                  void attempt(async () => {
                    await post("/setup-command", {
                      setup: { action: "discard", draft_id: id, expected_revision: draft.revision },
                    });
                    leaving.current = true;
                    setCreating(true);
                    window.location.assign("/setups");
                  })
                }
              >
                Discard draft
              </button>
            )}
          </div>
          <p role="status">
            {busy
              ? "Saving setup…"
              : draft
                ? dirty
                  ? "Unsaved changes"
                  : `Setup saved · ${time(draft.saved)}`
                : "Not saved yet"}
          </p>
        </form>
      </section>
    </>
  );
}

function ReviewAssignment({
  id,
  review,
  onRead,
}: {
  id: string;
  review?: Setup;
  onRead: Dispatch<SetStateAction<Setup | undefined>>;
}) {
  const read = useRead<Setup>(`/admin-api/setup-status/${id}`);
  useEffect(() => {
    if (read.data?.review_hash) onRead((prior) => prior ?? read.data);
  }, [read.data, onRead]);
  return (
    <>
      <p role="status">
        {read.failed
          ? "The assignment could not be checked. Your saved setup remains available."
          : !review
            ? "Checking assigned demo address…"
            : "Assigned demo address checked."}
      </p>
      {review && (
        <dl>
          <dt>Assigned URL</dt>
          <dd>https://{review.hostname}</dd>
          <dt>Storage and isolation</dt>
          <dd>
            Private 250 MiB workspace; 50 MiB file limit. Unique service identity and port; no
            existing workspace is copied.
          </dd>
        </dl>
      )}
    </>
  );
}

function SetupProgress({ initial }: { initial: Setup }) {
  const read = useRead<Setup>(`/admin-api/setup-status/${initial.id}`, 2000);
  const value = read.data ?? initial;
  const [notice, setNotice] = useState(""),
    [busy, setBusy] = useState(false),
    [credential, setCredential] = useState("");
  const op = value.operation;
  const control = async (action: string) => {
    if (!op) return;
    setBusy(true);
    setNotice("");
    try {
      await post(`/${action}`, {
        operation_id: op.id,
        expected_revision: op.revision,
        ...(action === "resume" ? { credential } : {}),
      });
      setCredential("");
      setNotice("Request recorded. Checking operation progress…");
    } catch (failure) {
      setNotice(failure instanceof Error ? failure.message : "Check the original operation.");
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <a className="back" href="/setups">
        ← Back to Saved setups
      </a>
      <h1>{value.data.name} — Setup progress</h1>
      {(read.expired || read.failed) && (
        <p role="alert">
          {read.expired
            ? "Your session ended. Sign in again at this same address to resume the setup."
            : "Connection unavailable. Retained progress may be stale; no new operation was submitted."}
        </p>
      )}
      <section className="panel">
        <h2>{words(value.lifecycle ?? op?.state ?? "provisioning")}</h2>
        <p>
          {value.data.email} · {value.hostname}
        </p>
        <p>
          Business access remains blocked until identity approval, recovery verification and
          explicit onboarding completion.
        </p>
        <ol>
          {op?.steps.map((step) => (
            <li key={step.kind}>
              {words(step.kind)} — {words(step.state)}
            </li>
          ))}
        </ol>
        {op?.state === "waiting" &&
          op.steps.find((step) => step.state !== "verified")?.kind === "provider_setup" && (
            <div className="notice">
              <h3>Administrator setup required</h3>
              <p>
                In Cloudflare, create a self-hosted Access application for exactly {value.hostname}{" "}
                with one Allow policy including only {value.data.email}. Do this before publishing
                the exact hostname’s route. Keep the catch-all deny route. The private verifier
                checks the application, audience, policy, configured route and unauthenticated
                public challenge independently.
              </p>
              <p>
                Follow HOSTED_ADMIN_PROVISIONING on the host. No provider token, passphrase or
                success checkbox belongs in this page.
              </p>
            </div>
          )}
        {op?.state === "waiting" &&
          op.steps.find((step) => step.state !== "verified")?.kind === "readiness" && (
            <div className="notice">
              <h3>Verify the pre-enrollment recovery point</h3>
              <p>
                Create, publish and independently validate the encrypted recovery point using the
                private terminal. Keep its passphrase out of this browser.
              </p>
              <code>{`sudo /opt/epm/admin/venv/bin/python -I /opt/epm/admin/admin_console.py verify-pre-enrollment --operation ${op.id}`}</code>
              <p>
                After the report verifies, obtain a fresh resume credential below. This does not
                complete approved-binding recovery or enable access.
              </p>
            </div>
          )}
        {op && !["succeeded", "cancelled"].includes(op.state) && (
          <div className="actions">
            <button
              disabled={busy || read.failed || read.expired}
              onClick={() => void control("cancel")}
            >
              Stop setup — retain resources
            </button>
            {["waiting", "unknown", "failed", "paused"].includes(op.state) && (
              <>
                <label>
                  One-use resume credential
                  <input
                    type="password"
                    name="resume-credential"
                    value={credential}
                    onChange={(e) => setCredential(e.target.value)}
                    autoComplete="off"
                  />
                </label>
                <p>
                  Private launcher: <code>{`epm-admin operations`}</code> with{" "}
                  <code>{JSON.stringify({ action: "resume-grant", identifier: op.id })}</code>.
                  Review the current operation before obtaining the credential.
                </p>
                <button
                  disabled={busy || !credential || read.failed || read.expired}
                  onClick={() => void control("resume")}
                >
                  Resume reviewed setup
                </button>
              </>
            )}
          </div>
        )}
        {value.operation_id && (
          <a href={`/operations/${value.operation_id}`}>View operation history</a>
        )}
        <p role="status">{notice}</p>
      </section>
      {value.invitation && (
        <section className="panel">
          <h2>Invitation to send manually</h2>
          <textarea aria-label="Invitation" readOnly value={value.invitation} rows={10} />
          <button
            disabled={read.failed || read.expired}
            onClick={() => {
              void navigator.clipboard
                .writeText(value.invitation ?? "")
                .then(() =>
                  setNotice("Invitation copied. This does not confirm delivery or enable access."),
                )
                .catch(() =>
                  setNotice(
                    "Select and copy the invitation text. Copying does not confirm delivery.",
                  ),
                );
            }}
          >
            Copy invitation
          </button>
        </section>
      )}
      {value.enrollment && <Approval value={value} unavailable={read.failed || read.expired} />}
    </>
  );
}

function Approval({ value, unavailable }: { value: Setup; unavailable: boolean }) {
  const [operationId] = useState(crypto.randomUUID());
  const [credential, setCredential] = useState(""),
    [authorized, setAuthorized] = useState(false),
    [busy, setBusy] = useState(false),
    [notice, setNotice] = useState("");
  const status = value.enrollment?.status;
  const [subject, setSubject] = useState("");
  const selected = status?.enrollments.find((item) => item.subject === subject);
  if (value.enrollment?.approved)
    return (
      <section className="panel">
        <h2>Identity approved</h2>
        <p>
          Recovery verification pending · Business access blocked. Complete the persistent recovery
          checklist after the Slice 6 recovery tooling is installed. No ready-to-use message is
          available yet.
        </p>
      </section>
    );
  if (!status) return null;
  const command = {
    operation_id: operationId,
    instance: value.instance,
    action: "approve",
    expected_revision: status.admin_revision,
    expected_binding_revision: status.binding_revision,
    fence: status.admin_fence,
    subject: selected?.subject,
    enrollment_received_at: selected?.received_at,
    reason: "Approve exact verified enrollment for isolated demo",
    confirmed: true,
  };
  const act = async (action: "reauthenticate" | "commands") => {
    setBusy(true);
    setNotice("");
    try {
      await post(`/${action}`, { command, ...(action === "reauthenticate" ? { credential } : {}) });
      setCredential("");
      if (action === "reauthenticate") {
        setAuthorized(true);
        setNotice("Action authorized. Review the identity and explicitly approve below.");
      } else {
        setAuthorized(false);
        setNotice(
          "Identity approved. Business access remains blocked pending recovery completion.",
        );
      }
    } catch (failure) {
      setNotice(
        failure instanceof Error
          ? failure.message
          : "Check the original approval operation before retrying.",
      );
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="panel">
      <h2>Review verified enrollment</h2>
      <p>
        Intended recipient: {value.data.email} · {value.hostname}. Confirm this is the intended
        person. Approving binds this exact verified subject and keeps business access blocked.
      </p>
      <dl>
        <dt>Verified issuer</dt>
        <dd>{value.enrollment?.issuer}</dd>
        <dt>Verified email</dt>
        <dd>{value.enrollment?.email}</dd>
      </dl>
      <label>
        Verified subject
        <select
          name="subject"
          value={subject}
          onChange={(e) => {
            setSubject(e.target.value);
            setAuthorized(false);
          }}
        >
          <option value="">Choose the pending enrollment</option>
          {status.enrollments.map((item) => (
            <option key={item.subject} value={item.subject}>
              {item.subject} · Received {time(item.received_at)}
            </option>
          ))}
        </select>
      </label>
      {selected && (
        <>
          <p>Private action-grant command input:</p>
          <pre>{JSON.stringify(command, null, 2)}</pre>
          <label>
            One-use action credential
            <input
              name="action-credential"
              type="password"
              value={credential}
              autoComplete="off"
              onChange={(e) => setCredential(e.target.value)}
            />
          </label>
          <div className="actions">
            <button
              disabled={busy || !credential || unavailable}
              onClick={() => void act("reauthenticate")}
            >
              Authorize reviewed approval
            </button>
            <button
              disabled={!authorized || busy || unavailable}
              onClick={() => void act("commands")}
            >
              Approve identity — keep access blocked
            </button>
            <a href={`/operations/${operationId}`}>Check original approval</a>
          </div>
        </>
      )}
      {!status.enrollments.length && (
        <p>
          No pending verified enrollment. The operator must sign in during the demo window and
          select Continue to workspace.
        </p>
      )}
      <p role="status">{notice}</p>
    </section>
  );
}
