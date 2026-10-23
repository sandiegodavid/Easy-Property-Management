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

export async function checkHostedResponse(response: Response) {
  if (!hostedMode() || ![401, 403, 503].includes(response.status)) return;
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
