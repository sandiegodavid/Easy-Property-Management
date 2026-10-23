import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { api } from "@epm/contracts";
import type { components } from "@epm/contracts/generated";
import { Page } from "@epm/ui";
import { admitHostedSession, hostedMode, pauseHostedSession } from "./hosted-session-state";

type Session = components["schemas"]["SessionResponse"];

function identity(session: Session) {
  return `${session.operatorId}:${session.workspaceId}:${session.identityBinding}`;
}

function destination() {
  const requested = new URLSearchParams(window.location.search).get("next") ?? "/home";
  const url = new URL(requested, window.location.origin);
  return url.origin === window.location.origin &&
    url.pathname !== "/sign-in" &&
    !url.pathname.startsWith("/api/")
    ? url.pathname + url.search
    : "/home";
}

function SessionGate({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const heading = useRef<HTMLHeadingElement>(null);
  const readSequence = useRef(0);
  const contact = document
    .querySelector('meta[name="epm-administrator-contact"]')
    ?.getAttribute("content");

  const read = useCallback((signal?: AbortSignal) => {
    const sequence = ++readSequence.current;
    return api
      .GET("/api/hosted/session", { signal })
      .then((result) => {
        if (signal?.aborted || sequence !== readSequence.current) return;
        if (!result.data || result.error)
          throw new Error("Sign in is required. Access may be expired or disabled.");
        const data = result.data;
        if (
          !data.operatorId ||
          !data.workspaceId ||
          !data.identityBinding ||
          !data.csrfToken ||
          !Number.isFinite(Date.parse(data.expiresAt)) ||
          Date.parse(data.expiresAt) <= Date.now()
        ) {
          throw new Error("The session response could not be verified.");
        }
        if (window.location.pathname === "/sign-in") {
          window.history.replaceState({}, "", destination());
        }
        admitHostedSession(data.csrfToken);
        setSession(data);
        setReady(true);
        setMessage("");
      })
      .catch((error: unknown) => {
        if (signal?.aborted || sequence !== readSequence.current) return;
        pauseHostedSession();
        setMessage(error instanceof Error ? error.message : "The session could not be checked.");
      });
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const pause = (event: Event) => {
      readSequence.current++;
      setReady(false);
      const detail: unknown = (event as CustomEvent<unknown>).detail;
      setMessage(
        typeof detail === "string"
          ? detail
          : "Session access is paused. Sign in explicitly to continue.",
      );
    };
    window.addEventListener("epm-session-paused", pause);
    const clearRuntime = () => setSession(null);
    window.addEventListener("epm-runtime-changed", clearRuntime);
    void read(controller.signal);
    return () => {
      controller.abort();
      window.removeEventListener("epm-session-paused", pause);
      window.removeEventListener("epm-runtime-changed", clearRuntime);
    };
  }, [read]);

  useEffect(() => {
    if (!ready) {
      document.title = "Sign in · Easy Property Management";
      heading.current?.focus();
      return;
    }
    if (!session) return;
    const timeout = window.setTimeout(
      () => {
        pauseHostedSession();
        setMessage("Your session expired. Editing is paused; sign in explicitly to continue.");
      },
      Math.max(0, Date.parse(session.expiresAt) - Date.now()),
    );
    const check = () => {
      if (document.visibilityState === "visible") void read();
    };
    window.addEventListener("focus", check);
    document.addEventListener("visibilitychange", check);
    const poll = window.setInterval(check, 60_000);
    return () => {
      clearTimeout(timeout);
      clearInterval(poll);
      window.removeEventListener("focus", check);
      document.removeEventListener("visibilitychange", check);
    };
  }, [ready, session, read]);

  async function signIn() {
    setBusy(true);
    try {
      const result = await api.POST("/api/hosted/session");
      if (!result.data || result.error) {
        const problem = result.error as { detail?: { code?: string } } | undefined;
        throw new Error(
          problem?.detail?.code === "hosted_enrollment_pending"
            ? "Enrollment is waiting for administrator approval. No workspace access has been granted."
            : "Sign in was not accepted. Renew Cloudflare sign-in or contact the administrator.",
        );
      }
      await read();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Sign in failed.");
    } finally {
      setBusy(false);
    }
  }

  async function signOut(all: boolean) {
    if (!session) return;
    const headers = { "X-EPM-CSRF": session.csrfToken };
    pauseHostedSession();
    setSession(null); // Unmount scoped caches, recovery and editors even on an uncertain response.
    setBusy(true);
    try {
      const result = all
        ? await api.DELETE("/api/hosted/session/all", { headers })
        : await api.DELETE("/api/hosted/session", { headers });
      setMessage(
        result.response.ok
          ? "Signed out. Renew Cloudflare sign-in before starting another session."
          : "Workspace closed, but sign-out could not be confirmed. Contact the administrator to revoke access.",
      );
    } catch {
      setMessage(
        "Workspace closed, but sign-out could not be confirmed. Contact the administrator to revoke access.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      {session && (
        <div key={identity(session)} hidden={!ready} inert={!ready}>
          <header className="hosted-session-banner" aria-label="Demo session">
            <p>Demo workspace — your changes are saved. Synthetic data only.</p>
            <p>
              Assigned workspace: {window.location.hostname}. Session active
              {session.capabilities.includes("records.write") ? "." : " — read-only."}
            </p>
            <p>
              Demo expires{" "}
              <time dateTime={session.demoExpiresAt}>
                {new Date(session.demoExpiresAt).toLocaleString()}
              </time>
              .
            </p>
            <button disabled={busy} onClick={() => void signOut(false)}>
              Sign out this device
            </button>
            <button disabled={busy} onClick={() => void signOut(true)}>
              Sign out all devices
            </button>
            <p>
              Administrator:{" "}
              <a href={`mailto:${session.administratorContact}`}>{session.administratorContact}</a>
            </p>
          </header>
          {children}
        </div>
      )}
      {!ready && (
        <Page title="Easy Property Management">
          <h2 ref={heading} tabIndex={-1}>
            Sign in to your demo workspace
          </h2>
          <p>
            Use the Cloudflare email sign-in for your assigned link. This demo accepts synthetic
            data only.
          </p>
          <p>Editing is paused. Nothing is automatically resubmitted after sign-in.</p>
          {message && <p role="alert">{message}</p>}
          <button disabled={busy} onClick={() => void signIn()}>
            {busy ? "Checking sign-in…" : "Continue to workspace"}
          </button>
          <p>
            <a href="/cdn-cgi/access/logout">
              Renew Cloudflare sign-in (signs out broader Access sessions)
            </a>
          </p>
          {contact && (
            <p>
              Contact the administrator: <a href={`mailto:${contact}`}>{contact}</a>
            </p>
          )}
        </Page>
      )}
    </>
  );
}

export function HostedSessionGate({ children }: { children: ReactNode }) {
  return hostedMode() ? <SessionGate>{children}</SessionGate> : children;
}
