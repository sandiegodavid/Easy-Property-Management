import { api } from "@epm/contracts";

let csrf: string | undefined;
let blocked = true;

export function hostedMode() {
  return (
    document.querySelector('meta[name="epm-deployment"]')?.getAttribute("content") === "hosted_demo"
  );
}

export function hostedWritesAllowed() {
  return !hostedMode() || !blocked;
}

export function pauseHostedSession(message?: string) {
  blocked = true;
  csrf = undefined;
  window.dispatchEvent(new CustomEvent("epm-session-paused", { detail: message }));
}

export function admitHostedSession(token: string) {
  csrf = token;
  blocked = false;
}

export function loadedRelease() {
  return document.querySelector('meta[name="epm-release"]')?.getAttribute("content") ?? null;
}

export function pauseForUpgrade(reload: boolean) {
  pauseHostedSession(
    reload
      ? "A new version is ready—reload to continue. Your unfinished work is preserved."
      : "Upgrade in progress. Your unfinished work is preserved.",
  );
  window.dispatchEvent(new CustomEvent("epm-upgrade", { detail: reload ? "reload" : "paused" }));
}

export function reloadForUpgrade() {
  const destination = { url: window.location.href };
  window.dispatchEvent(new CustomEvent("epm-upgrade-reload", { detail: destination }));
  window.location.assign(destination.url);
}

export async function checkHostedResponse(response: Response) {
  if (!hostedMode() || ![401, 403, 409, 503].includes(response.status)) return;
  const problem: unknown = await response
    .clone()
    .json()
    .catch(() => null);
  const code =
    problem &&
    typeof problem === "object" &&
    "detail" in problem &&
    problem.detail &&
    typeof problem.detail === "object" &&
    "code" in problem.detail
      ? problem.detail.code
      : null;
  if (response.status === 401) {
    // A definitive invalid session supersedes maintenance/reload presentation.
    // Keep mounted editors inert so explicit sign-in can recover their input.
    pauseHostedSession();
    window.dispatchEvent(new CustomEvent("epm-upgrade", { detail: null }));
    return;
  }
  if (code === "hosted_upgrade_in_progress" || code === "hosted_release_reload_required") {
    pauseForUpgrade(code === "hosted_release_reload_required");
    return;
  }
  if (
    typeof code === "string" &&
    /^hosted_(session_|identity_|assertion_|demo_|csrf_|workspace_)/.test(code)
  ) {
    pauseHostedSession(
      code === "hosted_workspace_unavailable"
        ? "The workspace is unavailable. Editing is paused; contact the administrator."
        : code === "hosted_demo_expired"
          ? "The demo is inactive or expired. Contact the administrator."
          : undefined,
    );
  }
}

api.use({
  onRequest({ request }) {
    if (!hostedMode()) return request;
    const release = loadedRelease();
    if (release) request.headers.set("X-EPM-Release", release);
    const sessionRoute = new URL(request.url).pathname.startsWith("/api/hosted/session");
    if (blocked && !sessionRoute) throw new Error("Sign in before continuing.");
    if (!["GET", "HEAD", "OPTIONS"].includes(request.method) && csrf) {
      request.headers.set("X-EPM-CSRF", csrf);
    }
    return request;
  },
  async onResponse({ response }) {
    await checkHostedResponse(response);
    return response;
  },
});
