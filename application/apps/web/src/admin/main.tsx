import { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { initializeApp, type FirebaseOptions } from "firebase/app";
import {
  initializeAuth,
  inMemoryPersistence,
  browserPopupRedirectResolver,
  GoogleAuthProvider,
  signInWithPopup,
  signOut,
  multiFactor,
  getMultiFactorResolver,
  TotpMultiFactorGenerator,
  type Auth,
  type MultiFactorError,
  type MultiFactorResolver,
  type TotpSecret,
} from "firebase/auth";
import "./style.css";
import { AdminWorkspace } from "./AdminWorkspace";
import type { AdminSession as Session } from "./admin-api";

interface Start {
  attemptId: string;
  firebase: FirebaseOptions;
  supportContact: string;
}
async function request<T>(path: string, value?: object, csrf?: string): Promise<T> {
  const response = await fetch(path, {
    signal: AbortSignal.timeout(10000),
    method: value ? "POST" : "GET",
    credentials: "same-origin",
    headers: {
      ...(value ? { "Content-Type": "application/json" } : {}),
      ...(csrf ? { "X-CSRF-Token": csrf } : {}),
    },
    body: value ? JSON.stringify(value) : undefined,
  });
  if (!response.ok)
    throw new Error("Unable to continue. Start sign-in again or contact the platform owner.");
  return (await response.json()) as T;
}
function Admin() {
  const [session, setSession] = useState<Session | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("Checking your Admin session…");
  const [step, setStep] = useState<"google" | "enroll" | "code">("google");
  const [code, setCode] = useState("");
  const [factorId, setFactorId] = useState("");
  const [factors, setFactors] = useState<{ uid: string; displayName?: string | null }[]>([]);
  const [secret, setSecret] = useState<TotpSecret | null>(null);
  const [support, setSupport] = useState("");
  const auth = useRef<Auth | null>(null);
  const attempt = useRef("");
  const resolver = useRef<MultiFactorResolver | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    void request<Session>("/api/admin/session").then(
      (value) => {
        setSession(value);
        setMessage("");
      },
      () => setMessage("Sign in with your approved Google account and authenticator."),
    );
  }, []);
  useEffect(() => {
    heading.current?.focus();
  }, [step, session]);

  async function google() {
    setBusy(true);
    setMessage("Opening Google sign-in…");
    try {
      const start = await request<Start>("/auth/start");
      attempt.current = start.attemptId;
      setSupport(start.supportContact);
      auth.current ??= initializeAuth(initializeApp(start.firebase), {
        persistence: inMemoryPersistence,
        popupRedirectResolver: browserPopupRedirectResolver,
      });
      const provider = new GoogleAuthProvider();
      provider.setCustomParameters({ prompt: "select_account" });
      try {
        const credential = await signInWithPopup(auth.current, provider);
        await request("/auth/complete", {
          attemptId: attempt.current,
          token: await credential.user.getIdToken(),
          phase: "enroll",
        });
        const generated = await TotpMultiFactorGenerator.generateSecret(
          await multiFactor(credential.user).getSession(),
        );
        setSecret(generated);
        setStep("enroll");
        setMessage("Add this setup key to your authenticator, then enter its six-digit code.");
      } catch (error) {
        if ((error as { code?: string }).code !== "auth/multi-factor-auth-required") throw error;
        resolver.current = getMultiFactorResolver(auth.current, error as MultiFactorError);
        if (
          !resolver.current.hints.some(
            (hint) => hint.factorId === TotpMultiFactorGenerator.FACTOR_ID,
          )
        ) {
          throw new Error("A supported authenticator is required. Contact the platform owner.");
        }
        const available = resolver.current.hints.filter(
          (hint) => hint.factorId === TotpMultiFactorGenerator.FACTOR_ID,
        );
        setFactors(available);
        setFactorId(available[0]?.uid ?? "");
        setStep("code");
        setMessage("Enter the code from your authenticator.");
      }
    } catch {
      setMessage(
        `Sign-in could not continue. Allow the Google popup and try again, or contact ${support || "the platform owner"}.`,
      );
    } finally {
      setBusy(false);
    }
  }

  async function verify(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      const current = auth.current;
      if (!current) throw new Error("Start sign-in again.");
      if (secret && current.currentUser) {
        await multiFactor(current.currentUser).enroll(
          TotpMultiFactorGenerator.assertionForEnrollment(secret, code),
          "Admin authenticator",
        );
        setSecret(null);
        setCode("");
        await signOut(current);
        setStep("google");
        setMessage("Authenticator added. Sign in again to verify it and open Admin.");
        return;
      }
      const pending = resolver.current;
      const factor = pending?.hints.find(
        (hint) => hint.factorId === TotpMultiFactorGenerator.FACTOR_ID && hint.uid === factorId,
      );
      if (!pending || !factor) throw new Error("Start sign-in again.");
      const credential = await pending.resolveSignIn(
        TotpMultiFactorGenerator.assertionForSignIn(factor.uid, code),
      );
      const saved = await request<Session>("/auth/complete", {
        attemptId: attempt.current,
        token: await credential.user.getIdToken(),
      });
      setSession(saved);
      setMessage("Signed in.");
      await signOut(current).catch(() => {
        setMessage(
          "Signed in. Close this tab when you finish to clear the temporary Google sign-in.",
        );
      });
      resolver.current = null;
      setCode("");
    } catch {
      setMessage(
        "The code or sign-in attempt could not be verified. Try the current code or start sign-in again.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function logout() {
    setBusy(true);
    try {
      await request("/auth/logout", {}, session?.csrfToken);
      setSession(null);
      setStep("google");
      setMessage("Signed out.");
    } catch {
      setMessage("Sign out could not be confirmed. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-busy={busy} className={session ? "admin-shell" : "auth-shell"}>
      <p className="brand">Easy Property Management</p>
      <div className="header-bar">
        <h1 tabIndex={-1} ref={heading}>
          {session ? "Admin" : "Admin sign-in"}
        </h1>
        {session && (
          <button
            type="button"
            disabled={busy || !session.csrfToken}
            onClick={() => {
              void logout();
            }}
          >
            Sign out
          </button>
        )}
      </div>
      <p role="status">{message}</p>
      {session ? (
        <>
          <p className="muted">Session ends {new Date(session.expiresAt).toLocaleString()}.</p>
          {!session.csrfToken && <p>Sign in again to manage this session.</p>}
          <AdminWorkspace session={session} />
        </>
      ) : step === "google" ? (
        <button
          type="button"
          disabled={busy}
          onClick={() => {
            void google();
          }}
        >
          Continue with Google
        </button>
      ) : (
        <form
          method="post"
          action="/auth/complete"
          onSubmit={(event) => {
            void verify(event);
          }}
        >
          {secret && (
            <>
              <h2>Set up your authenticator</h2>
              <p>Setup key</p>
              <code>{secret.secretKey}</code>
            </>
          )}
          {!secret && factors.length > 1 && (
            <>
              <label htmlFor="authenticator">Authenticator</label>
              <select
                id="authenticator"
                name="authenticator"
                value={factorId}
                onChange={(event) => setFactorId(event.target.value)}
              >
                {factors.map((hint, index) => (
                  <option key={hint.uid} value={hint.uid}>
                    {hint.displayName || `Authenticator ${index + 1}`}
                  </option>
                ))}
              </select>
            </>
          )}
          <label htmlFor="code">Authenticator code (required)</label>
          <input
            id="code"
            name="code"
            type="text"
            inputMode="numeric"
            autoComplete="one-time-code"
            required
            pattern="[0-9]{6}"
            maxLength={6}
            spellCheck={false}
            autoCapitalize="none"
            value={code}
            onChange={(event) => setCode(event.target.value)}
          />
          <button type="submit" disabled={busy}>
            {secret ? "Add authenticator" : "Verify and sign in"}
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              setSecret(null);
              resolver.current = null;
              setCode("");
              setFactorId("");
              setFactors([]);
              if (auth.current)
                void signOut(auth.current).catch(() => {
                  setMessage(
                    "Close this tab and sign in again to clear the temporary Google sign-in.",
                  );
                });
              setStep("google");
            }}
          >
            Start sign-in again
          </button>
        </form>
      )}
      <p>For account or authenticator recovery, contact {support || "the platform owner"}.</p>
    </section>
  );
}
const root = document.getElementById("root");
if (root) createRoot(root).render(<Admin />);
