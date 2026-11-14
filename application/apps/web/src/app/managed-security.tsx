import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Page } from "@epm/ui";
import { admitHostedSession, pauseHostedSession } from "./hosted-session-state";

const endpoint = "/api/hosted/session";
const storageKey = "epm-pending-sign-out";
const logoutSignal = "epm-managed-session-closed";

type Session = {
  identity: string;
  sessionId: string;
  expiresAt: number;
  renewAfter: number;
  csrfToken: string;
  supportContact: string | null;
  capabilities: string[];
};

type Device = {
  sessionId: string;
  label: string;
  lastSeenAt: number;
  current: boolean;
};

type SignOut = {
  operation: string;
  proof: string;
  selection: "current" | "all" | "other";
  device: string;
};

type Phase = "loading" | "active" | "signed_out" | "unavailable" | "resume" | "renewal_required";

function loadPending(): SignOut | null {
  try {
    return JSON.parse(sessionStorage.getItem(storageKey) ?? "null") as SignOut | null;
  } catch {
    return null;
  }
}

function setPending(value: SignOut | null) {
  try {
    if (value) sessionStorage.setItem(storageKey, JSON.stringify(value));
    else sessionStorage.removeItem(storageKey);
  } catch {
    // The current tab can still check the operation held in memory.
  }
}

function signOutIntent(selection: SignOut["selection"], device = ""): SignOut {
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  const proof = btoa(String.fromCharCode(...bytes))
    .replaceAll("+", "-")
    .replaceAll("/", "_")
    .replace(/=+$/, "");
  return { operation: crypto.randomUUID(), proof, selection, device };
}

function authStart(renew: boolean, returnTo: string) {
  const query = new URLSearchParams({ returnTo });
  if (renew) query.set("renew", "1");
  return "/auth/start?" + query.toString();
}

function request(path: string, init?: RequestInit) {
  return fetch(path, {
    ...init,
    cache: "no-store",
    credentials: "same-origin",
    signal: AbortSignal.timeout(8000),
  });
}

function parsedSession(value: Partial<Session>): Session {
  if (
    !value.identity ||
    !value.sessionId ||
    !value.csrfToken ||
    typeof value.expiresAt !== "number" ||
    !Number.isFinite(value.expiresAt) ||
    typeof value.renewAfter !== "number" ||
    !Number.isFinite(value.renewAfter) ||
    value.expiresAt <= Date.now() ||
    value.renewAfter > value.expiresAt
  ) {
    throw new Error("The workspace session could not be verified.");
  }
  return {
    identity: value.identity,
    sessionId: value.sessionId,
    csrfToken: value.csrfToken,
    expiresAt: value.expiresAt,
    renewAfter: value.renewAfter,
    supportContact: value.supportContact ?? null,
    capabilities: Array.isArray(value.capabilities) ? value.capabilities : [],
  };
}

export function ManagedSecurity({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const current = useRef<Session | null>(null);
  const [pending, setPendingState] = useState<SignOut | null>(loadPending);
  const [phase, setPhase] = useState<Phase>(
    pending && pending.selection !== "other" ? "signed_out" : "loading",
  );
  const phaseRef = useRef<Phase>(phase);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [devices, setDevices] = useState<Device[] | null>(null);
  const [devicesError, setDevicesError] = useState("");
  const [open, setOpen] = useState(false);
  const [confirmation, setConfirmation] = useState<{
    selection: SignOut["selection"];
    device?: Device;
  } | null>(null);
  const [fallback, setFallback] = useState(false);
  const [renewal, setRenewal] = useState(false);
  const pendingRef = useRef(pending);
  const dialog = useRef<HTMLDialogElement>(null);
  const continueFocus = useRef<HTMLElement | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const requestSequence = useRef(0);
  const checking = useRef(false);
  const popup = useRef<Window | null>(null);
  const renewalBaseline = useRef<string | null>(null);
  const closed = useRef<string | null>(null);
  const invalidate = useCallback(() => {
    requestSequence.current++;
  }, []);

  const transition = useCallback((next: Phase) => {
    if (phaseRef.current === "active" && next !== "active") {
      continueFocus.current =
        document.activeElement instanceof HTMLElement ? document.activeElement : null;
    }
    phaseRef.current = next;
    setPhase(next);
  }, []);

  const remember = useCallback((value: SignOut | null) => {
    pendingRef.current = value;
    setPendingState(value);
    setPending(value);
  }, []);

  const clearScope = useCallback(() => {
    current.current = null;
    setSession(null);
    setDevices(null);
    setOpen(false);
    continueFocus.current = null;
    window.dispatchEvent(new Event("epm-runtime-changed"));
  }, []);

  const check = useCallback(async () => {
    if (checking.current || (pendingRef.current && pendingRef.current.selection !== "other"))
      return;
    checking.current = true;
    const sequence = ++requestSequence.current;
    try {
      let response = await request(endpoint);
      const prior = current.current;
      let payload: unknown = await response.json();
      if (sequence !== requestSequence.current) return;
      if (
        response.status === 503 &&
        payload &&
        typeof payload === "object" &&
        "refreshCsrf" in payload &&
        typeof payload.refreshCsrf === "string"
      ) {
        pauseHostedSession();
        response = await request(endpoint + "/refresh", {
          method: "POST",
          headers: { "X-EPM-CSRF": payload.refreshCsrf },
        });
        payload = await response.json();
      }
      if (sequence !== requestSequence.current) return;
      if (!response.ok) {
        const state =
          payload && typeof payload === "object" && "state" in payload ? payload.state : null;
        if (renewalBaseline.current && response.status === 401) return;
        pauseHostedSession();
        transition(
          response.status === 503
            ? "unavailable"
            : state === "renewal_required"
              ? "renewal_required"
              : "signed_out",
        );

        return;
      }
      const value = parsedSession(payload as Partial<Session>);
      if (renewalBaseline.current === value.sessionId || closed.current === value.sessionId) return;
      try {
        if (localStorage.getItem(logoutSignal) === value.sessionId) {
          closed.current = value.sessionId;
          pauseHostedSession();
          transition("signed_out");
          return;
        }
      } catch {
        // In-memory sign-out still applies when storage is unavailable.
      }
      if (prior && prior.identity !== value.identity) clearScope();
      current.current = value;
      setSession(value);
      setMessage("");
      const requiresContinue = Boolean(
        prior &&
        (prior.identity !== value.identity ||
          phaseRef.current === "resume" ||
          (phaseRef.current !== "active" && phaseRef.current !== "loading") ||
          prior.sessionId !== value.sessionId),
      );
      if (requiresContinue) {
        pauseHostedSession();
        transition("resume");
      } else {
        admitHostedSession(value.csrfToken);
        transition("active");
      }
      if (renewalBaseline.current !== null) {
        renewalBaseline.current = null;
        popup.current?.close();
        popup.current = null;
        setRenewal(false);
        setFallback(false);
      }
    } catch {
      if (sequence === requestSequence.current) {
        pauseHostedSession();
        transition("unavailable");
      }
    } finally {
      checking.current = false;
    }
  }, [clearScope, transition]);

  useEffect(() => {
    const initial = window.setTimeout(() => void check(), 0);
    const changed = (event: StorageEvent) => {
      if (
        event.key !== logoutSignal ||
        !event.newValue ||
        (current.current && current.current.sessionId !== event.newValue)
      )
        return;
      requestSequence.current++;
      closed.current = event.newValue;
      pauseHostedSession();
      clearScope();
      transition("signed_out");
      setMessage("Workspace access ended in another tab.");
    };
    const focused = () => {
      if (document.visibilityState === "visible") void check();
    };
    const poll = window.setInterval(focused, 60_000);
    const paused = () => {
      if (phaseRef.current === "active") transition("unavailable");
    };
    window.addEventListener("storage", changed);
    window.addEventListener("focus", focused);
    window.addEventListener("epm-session-paused", paused);
    document.addEventListener("visibilitychange", focused);
    return () => {
      clearTimeout(initial);
      clearInterval(poll);
      invalidate();
      checking.current = false;
      window.removeEventListener("storage", changed);
      window.removeEventListener("focus", focused);
      window.removeEventListener("epm-session-paused", paused);
      document.removeEventListener("visibilitychange", focused);
    };
  }, [check, clearScope, invalidate, transition]);

  useEffect(() => {
    if (phase !== "active") heading.current?.focus({ preventScroll: true });
    if (!session || phase !== "active") return;
    const timer = window.setTimeout(
      () => {
        pauseHostedSession();
        transition(session.expiresAt <= Date.now() ? "renewal_required" : "unavailable");
        void check();
      },
      Math.max(0, session.renewAfter - Date.now()),
    );
    return () => clearTimeout(timer);
  }, [check, phase, session, transition]);

  useEffect(() => {
    if (!renewal) return;
    const timer = window.setInterval(() => {
      void check();
      if (popup.current?.closed) {
        popup.current = null;
        setFallback(true);
      }
    }, 1500);
    return () => clearInterval(timer);
  }, [check, renewal]);

  const list = useCallback(async () => {
    const sessionId = current.current?.sessionId;
    setDevicesError("");
    try {
      const response = await request("/api/hosted/sessions");
      if (!response.ok) throw new Error();
      const result = (await response.json()) as { items: Device[] };
      if (current.current?.sessionId === sessionId) setDevices(result.items);
    } catch {
      setDevicesError("The device list is temporarily unavailable.");
    }
  }, []);

  useEffect(() => {
    if (!(open && phase === "active")) return;
    const read = window.setTimeout(() => void list(), 0);
    return () => clearTimeout(read);
  }, [list, open, phase]);
  useEffect(() => {
    if (confirmation && dialog.current && !dialog.current.open) dialog.current.showModal();
  }, [confirmation]);

  function renew(renewExisting = true) {
    renewalBaseline.current = current.current?.sessionId ?? "";
    const child = window.open("about:blank", "_blank", "popup,width=540,height=680");
    if (child) {
      child.opener = null;
      child.location.replace(authStart(renewExisting, "/sign-in"));
    }
    popup.current = child;
    setFallback(!child);
    setRenewal(true);
  }

  function resume() {
    if (!session || session.renewAfter <= Date.now()) {
      void check();
      return;
    }
    admitHostedSession(session.csrfToken);
    transition("active");
    requestAnimationFrame(() => continueFocus.current?.focus({ preventScroll: true }));
  }

  async function revoke(intent: SignOut, checkOnly = false) {
    const csrf = current.current?.csrfToken;
    remember(intent);
    setBusy(true);
    if (intent.selection !== "other" && !checkOnly) {
      requestSequence.current++;
      pauseHostedSession();
      closed.current = current.current?.sessionId ?? null;
      clearScope();
      transition("signed_out");
      setRenewal(false);
      renewalBaseline.current = null;
      try {
        localStorage.setItem(logoutSignal, closed.current ?? intent.operation);
      } catch {
        /* This tab is already closed. */
      }
    }
    try {
      const response = await request(endpoint + (checkOnly ? "/logout/check" : "/logout"), {
        method: "POST",
        headers: { "X-EPM-CSRF": csrf ?? "" },
        body: new URLSearchParams(intent),
      });
      const result = (await response.json()) as { state: string };
      if (response.ok && result.state === "confirmed") {
        remember(null);
        setMessage(intent.selection === "other" ? "Device signed out." : "Signed out.");
      } else {
        setMessage(
          result.state === "pending"
            ? "Workspace sign-out was recorded. Central sign-out still needs checking."
            : "Sign-out could not be confirmed. Check its status.",
        );
      }
    } catch {
      setMessage("Sign-out could not be confirmed. Check its status.");
    } finally {
      setBusy(false);
      if (intent.selection === "other") void list();
    }
  }

  const active = phase === "active";
  const support =
    session?.supportContact ??
    document.querySelector('meta[name="epm-administrator-contact"]')?.getAttribute("content");
  return (
    <>
      {session && (
        <div key={session.identity} hidden={!active} inert={!active}>
          <header className="hosted-session-banner" aria-label="Workspace security">
            <button type="button" aria-expanded={open} onClick={() => setOpen(!open)}>
              Security
            </button>
            <button type="button" onClick={() => renew()}>
              Renew sign-in
            </button>
            {open && (
              <section aria-label="Security">
                <p>
                  Sign-in expires{" "}
                  <time dateTime={new Date(session.expiresAt).toISOString()}>
                    {new Date(session.expiresAt).toLocaleString()}
                  </time>
                  .
                </p>
                <h2>Signed-in devices</h2>
                {devicesError ? (
                  <p role="alert">
                    {devicesError}{" "}
                    <button type="button" onClick={() => void list()}>
                      Retry
                    </button>
                  </p>
                ) : devices === null ? (
                  <p role="status">Loading devices…</p>
                ) : devices.length === 0 ? (
                  <p>No active devices.</p>
                ) : (
                  <ul>
                    {devices.map((device) => (
                      <li key={device.sessionId}>
                        {device.label}
                        {device.current ? " · This device" : ""} ·{" "}
                        <time dateTime={new Date(device.lastSeenAt).toISOString()}>
                          {new Date(device.lastSeenAt).toLocaleString()}
                        </time>
                        {!device.current && (
                          <button
                            type="button"
                            disabled={busy || pending !== null}
                            onClick={() => setConfirmation({ selection: "other", device })}
                          >
                            Sign out device
                          </button>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
                <button
                  type="button"
                  disabled={busy || pending !== null}
                  onClick={() => setConfirmation({ selection: "current" })}
                >
                  Sign out this device
                </button>
                <button
                  type="button"
                  disabled={busy || pending !== null}
                  onClick={() => setConfirmation({ selection: "all" })}
                >
                  Sign out all devices
                </button>
              </section>
            )}
          </header>
          {session.capabilities.includes("records.read") ? (
            children
          ) : (
            <Page title="Workspace access">
              <p>Your sign-in is verified. Workspace features are not available yet.</p>
            </Page>
          )}
        </div>
      )}
      {(!active || fallback || renewal || message || pending) && (
        <Page title="Workspace sign-in">
          {!active && (
            <h2 ref={heading} tabIndex={-1}>
              {phase === "resume"
                ? "Sign-in verified"
                : phase === "loading"
                  ? "Checking your session"
                  : phase === "unavailable"
                    ? "Sign-in is temporarily unavailable"
                    : phase === "renewal_required"
                      ? "Renew your sign-in"
                      : "Sign in to your workspace"}
            </h2>
          )}
          {!active && session && (
            <p>
              Editing is paused. Your form stays open, and no changes will be submitted
              automatically.
            </p>
          )}
          {message && <p role="status">{message}</p>}
          {phase === "resume" && (
            <button type="button" onClick={resume}>
              Continue to workspace
            </button>
          )}
          {phase === "unavailable" && (
            <button type="button" onClick={() => void check()}>
              Check session
            </button>
          )}
          {phase === "renewal_required" && (
            <button type="button" onClick={() => renew()}>
              Renew sign-in
            </button>
          )}
          {renewal && !fallback && (
            <p role="status">Complete sign-in in the new window, then return here.</p>
          )}
          {renewal && (
            <button
              type="button"
              onClick={() => {
                popup.current?.close();
                popup.current = null;
                renewalBaseline.current = null;
                setFallback(false);
                setRenewal(false);
              }}
            >
              Cancel sign-in
            </button>
          )}
          {fallback && (
            <>
              <p>
                The sign-in window could not be used. Save or copy your unfinished input before
                continuing in this tab.
              </p>
              <a href={authStart(phase !== "signed_out" && Boolean(session), "/sign-in")}>
                Continue sign-in in this tab
              </a>
            </>
          )}
          {phase === "signed_out" && !pending && (
            <button type="button" onClick={() => renew(false)}>
              Start sign-in
            </button>
          )}
          {pending && (
            <button type="button" disabled={busy} onClick={() => void revoke(pending, true)}>
              Check sign-out status
            </button>
          )}
          {support && (
            <p>
              Need help? <a href={"mailto:" + support}>{support}</a>
            </p>
          )}
        </Page>
      )}
      <dialog
        ref={dialog}
        className="managed-security-dialog"
        aria-labelledby="sign-out-heading"
        onClose={() => setConfirmation(null)}
      >
        {confirmation && (
          <>
            <h2 id="sign-out-heading">Confirm sign-out</h2>
            <p>
              {confirmation.selection === "all"
                ? "This ends workspace access on every signed-in device."
                : confirmation.selection === "current"
                  ? "This ends workspace access in this browser."
                  : "This ends workspace access on the selected device."}
            </p>
            <form method="dialog">
              <button>Cancel</button>
              <button
                type="button"
                onClick={() => {
                  dialog.current?.close();
                  void revoke(
                    signOutIntent(confirmation.selection, confirmation.device?.sessionId),
                  );
                }}
              >
                Confirm sign-out
              </button>
            </form>
          </>
        )}
      </dialog>
    </>
  );
}
