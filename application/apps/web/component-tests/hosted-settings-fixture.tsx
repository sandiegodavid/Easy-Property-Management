import { useState } from "react";
import { createRoot } from "react-dom/client";
import { HostedMaintenanceBanner, HostedSettings } from "../src/app/hosted-settings";
import { mutation, MutationFailure } from "../src/shared/mutations";

const params = new URLSearchParams(window.location.search);
if (params.get("mode") === "hosted") {
  const meta = document.createElement("meta");
  meta.name = "epm-deployment";
  meta.content = "hosted_managed";
  document.head.appendChild(meta);
}

function StorageLimitForm() {
  const [note, setNote] = useState("");
  const [status, setStatus] = useState("");
  const [outcomeFlag, setOutcomeFlag] = useState("");

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setStatus("");
    setOutcomeFlag("");
    try {
      await mutation(async () => {
        const response = await fetch("/api/properties", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: note }),
        });
        const body: unknown = await response.json().catch(() => null);
        return response.ok ? { data: body, response } : { error: body, response };
      });
      setStatus("Saved");
    } catch (error) {
      if (error instanceof MutationFailure) {
        setStatus(error.problem.message);
        setOutcomeFlag(error.outcomeUnknown ? "unknown" : "definite");
      } else {
        setStatus("Unexpected error");
      }
    }
  }

  return (
    <form onSubmit={(event) => void onSubmit(event)}>
      <label htmlFor="draft-property-name">Property name</label>
      <input
        id="draft-property-name"
        value={note}
        onChange={(event) => setNote(event.target.value)}
      />
      <button type="submit">Save property</button>
      {status && <p role="alert">{status}</p>}
      {outcomeFlag && <p data-testid="outcome-flag">{outcomeFlag}</p>}
    </form>
  );
}

createRoot(document.getElementById("root")!).render(
  <main>
    <HostedMaintenanceBanner />
    <h1>Settings</h1>
    <HostedSettings />
    <StorageLimitForm />
  </main>,
);
