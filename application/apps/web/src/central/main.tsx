import { useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { initializeApp, type FirebaseOptions } from "firebase/app";
import {
  initializeAuth,
  inMemoryPersistence,
  browserPopupRedirectResolver,
  GoogleAuthProvider,
  signInWithPopup,
  signOut,
  getMultiFactorResolver,
  TotpMultiFactorGenerator,
  type Auth,
  type MultiFactorError,
  type MultiFactorResolver,
} from "firebase/auth";
import "../admin/style.css";

declare global {
  interface Window {
    epmEmailCompletion?: { code: string | null; attempt: string | null };
  }
}
const emailCompletion = window.epmEmailCompletion;
delete window.epmEmailCompletion;
const searchParams = new URLSearchParams(location.search);
const flow = searchParams.get("flow");
const source = searchParams.get("source");

interface Outcome {
  state: string;
  continuationId?: string;
  continueUrl?: string;
  handoffAttempt?: string;
}
interface Start {
  attemptId: string;
  firebase: FirebaseOptions;
}
async function request<T>(path: string, body?: object): Promise<T> {
  const response = await fetch(path, {
    method: body ? "POST" : "GET",
    credentials: "same-origin",
    signal: AbortSignal.timeout(10000),
    headers: {
      Accept: "application/json",
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok)
    throw new Error(
      "Sign-in could not be completed. Request a new link or start again from your workspace.",
    );
  return (await response.json()) as T;
}
function Login() {
  const [emailMode] = useState(Boolean(emailCompletion?.code && emailCompletion.attempt));
  const [email, setEmail] = useState("");
  const [remembered, setRemembered] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [result, setResult] = useState<Outcome | null>(null);
  const [pendingEmail, setPendingEmail] = useState("");
  const [factors, setFactors] = useState<{ uid: string; displayName?: string | null }[]>([]);
  const [factorId, setFactorId] = useState("");
  const [code, setCode] = useState("");
  const auth = useRef<Auth | null>(null);
  const attempt = useRef("");
  const resolver = useRef<MultiFactorResolver | null>(null);
  const capability = useRef(emailCompletion);
  const codeInput = useRef<HTMLInputElement>(null);

  async function exchange(token: string) {
    const saved = await request<Outcome>("/auth/complete", {
      attemptId: attempt.current,
      token,
      remembered,
    });
    setResult(saved);
    setMessage(
      saved.handoffAttempt
        ? "Identity verified."
        : "Identity verified. Workspace setup is not ready yet.",
    );
    if (auth.current)
      await signOut(auth.current).catch(() => {
        setMessage(
          "Identity verified. Close this tab after finishing to clear temporary sign-in details.",
        );
      });
    resolver.current = null;
    setCode("");
  }

  async function google() {
    if (!flow) return;
    setBusy(true);
    try {
      const start = await request<Start>(
        `/auth/start?flow=${encodeURIComponent(flow)}&method=google${source ? `&source=${encodeURIComponent(source)}` : ""}`,
      );
      attempt.current = start.attemptId;
      auth.current ??= initializeAuth(initializeApp(start.firebase), {
        persistence: inMemoryPersistence,
        popupRedirectResolver: browserPopupRedirectResolver,
      });
      const provider = new GoogleAuthProvider();
      provider.setCustomParameters({ prompt: "select_account" });
      try {
        const user = await signInWithPopup(auth.current, provider);
        await exchange(await user.user.getIdToken());
      } catch (error) {
        if ((error as { code?: string }).code !== "auth/multi-factor-auth-required") throw error;
        resolver.current = getMultiFactorResolver(auth.current, error as MultiFactorError);
        const choices = resolver.current.hints.filter(
          (hint) => hint.factorId === TotpMultiFactorGenerator.FACTOR_ID,
        );
        if (!choices.length) throw new Error("Use an approved authenticator to continue.");
        setFactors(choices);
        setFactorId(choices[0]?.uid ?? "");
        setMessage("Enter your authenticator code.");
        queueMicrotask(() => codeInput.current?.focus());
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Sign-in is unavailable.");
    } finally {
      setBusy(false);
    }
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      if (capability.current?.attempt && capability.current.code) {
        const saved = await request<Outcome>("/auth/email/continue", {
          attemptId: capability.current.attempt,
          code: capability.current.code,
          email,
          remembered,
        });
        capability.current.code = null;
        capability.current.attempt = null;
        capability.current = undefined;
        setResult(saved);
        setMessage(
          saved.state === "unknown"
            ? "This submission needs checking. Request a new link to start again."
            : "Your identity has been checked. Continue in your workspace.",
        );
      } else if (resolver.current) {
        const user = await resolver.current.resolveSignIn(
          TotpMultiFactorGenerator.assertionForSignIn(factorId, code),
        );
        await exchange(await user.user.getIdToken());
      } else if (flow) {
        const sent = await request<{ attemptId: string }>("/auth/email-link", {
          flowId: flow,
          ...(source ? { source } : {}),
          email,
        });
        setPendingEmail(sent.attemptId);
        setMessage(
          "Check your email for a sign-in link. You can open it on this or another device.",
        );
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Sign-in is unavailable.");
    } finally {
      setBusy(false);
    }
  }

  async function check() {
    setBusy(true);
    try {
      const status = await request<Outcome>(
        `/auth/start?attempt=${encodeURIComponent(pendingEmail)}`,
      );
      setMessage(
        status.state === "superseded"
          ? "This link is being completed on another device."
          : "Waiting for your email link to be completed.",
      );
    } catch {
      setMessage("This attempt is unavailable. Request a new link for this device.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-busy={busy}>
      <p className="brand">Easy Property Management</p>
      <h1>Sign in to your workspace</h1>
      <p role="status">{message}</p>
      {result ? (
        <>
          {result.continueUrl && <a href={result.continueUrl}>Continue to your workspace</a>}
          {result.handoffAttempt ? (
            <form action="/auth/complete" method="post">
              <input name="attemptId" type="hidden" value={result.handoffAttempt} />
              <button type="submit">Continue to your workspace</button>
            </form>
          ) : (
            <p>You can return to your workspace to start a new sign-in.</p>
          )}
        </>
      ) : !flow && !emailMode ? (
        <p>Open Sign in from your workspace, or request a new email link.</p>
      ) : (
        <>
          {!emailMode && !factors.length && (
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                void google();
              }}
            >
              Continue with Google
            </button>
          )}
          <form
            method="post"
            action={emailMode ? "/auth/email/continue" : "/auth/email-link"}
            onSubmit={(event) => {
              void submit(event);
            }}
          >
            {factors.length ? (
              <>
                <label htmlFor="factor">Authenticator</label>
                <select
                  id="factor"
                  name="factor"
                  value={factorId}
                  onChange={(event) => setFactorId(event.target.value)}
                >
                  {factors.map((factor, index) => (
                    <option key={factor.uid} value={factor.uid}>
                      {factor.displayName || `Authenticator ${index + 1}`}
                    </option>
                  ))}
                </select>
                <label htmlFor="code">Authenticator code (required)</label>
                <input
                  id="code"
                  name="code"
                  ref={codeInput}
                  type="text"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  pattern="[0-9]{6}"
                  maxLength={6}
                  required
                  value={code}
                  onChange={(event) => setCode(event.target.value)}
                />
              </>
            ) : (
              <>
                <label htmlFor="email">Email address (required)</label>
                <input
                  id="email"
                  name="email"
                  type="email"
                  autoComplete="email"
                  required
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                />
              </>
            )}
            <label>
              <input
                type="checkbox"
                checked={remembered}
                onChange={(event) => setRemembered(event.target.checked)}
              />
              Remember this browser
            </label>
            <button type="submit" disabled={busy}>
              {factors.length || emailMode ? "Verify and continue" : "Email me a sign-in link"}
            </button>
          </form>
          {pendingEmail && (
            <>
              <button
                type="button"
                disabled={busy}
                onClick={() => {
                  void check();
                }}
              >
                Check sign-in status
              </button>
              <p>Request a new link above to complete sign-in on this device.</p>
            </>
          )}
        </>
      )}
    </section>
  );
}
const root = document.getElementById("root");
if (root) createRoot(root).render(<Login />);
