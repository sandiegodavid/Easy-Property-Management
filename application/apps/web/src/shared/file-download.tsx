import { useEffect, useRef, useState, type ReactNode, type MouseEvent } from "react";
import { checkHostedResponse, hostedMode, hostedWritesAllowed } from "../app/hosted-session-state";

// Local mode retains native downloads. Hosted mode checks authorization before
// releasing bytes and never navigates a paused editor to an API error document.
export function FileDownload({
  fileId,
  name,
  children,
}: {
  fileId: string;
  name?: string;
  children: ReactNode;
}) {
  const href = `/api/files/${fileId}/content`;
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const request = useRef<AbortController | null>(null);
  useEffect(() => {
    const cancel = () => request.current?.abort();
    window.addEventListener("epm-session-paused", cancel);
    return () => {
      cancel();
      window.removeEventListener("epm-session-paused", cancel);
    };
  }, []);

  async function download(event: MouseEvent<HTMLAnchorElement>) {
    if (!hostedMode()) return;
    event.preventDefault();
    if (busy || !hostedWritesAllowed()) return;
    const controller = new AbortController();
    request.current = controller;
    setBusy(true);
    setError("");
    try {
      const response = await fetch(href, { signal: controller.signal, cache: "no-store" });
      await checkHostedResponse(response);
      if (!response.ok)
        throw new Error("Download unavailable. Check access or contact the administrator.");
      const blob = await response.blob();
      if (controller.signal.aborted || !hostedWritesAllowed()) return;
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = name ?? "evidence";
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch {
      if (!controller.signal.aborted)
        setError("Download failed. Try again explicitly when access is available.");
    } finally {
      request.current = null;
      setBusy(false);
    }
  }

  return (
    <>
      <a
        href={href}
        download={name ?? true}
        aria-disabled={busy}
        onClick={(event) => void download(event)}
      >
        {busy ? "Preparing download…" : children}
      </a>
      {error && <p role="alert">{error}</p>}
    </>
  );
}
