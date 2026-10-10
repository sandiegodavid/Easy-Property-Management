import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { api } from "@epm/contracts";
import { Page } from "@epm/ui";
import "./style.css";

function App() {
  const [connection, setConnection] = useState("Checking local connection…");
  useEffect(() => {
    const controller = new AbortController();
    void api
      .GET("/api/operator/bootstrap", { signal: controller.signal })
      .then(({ data, error }) => {
        if (controller.signal.aborted) return;
        setConnection(
          error || !data
            ? "Local connection unavailable."
            : data.state === "ready"
              ? "Local workspace connected."
              : "Local workspace unavailable.",
        );
      })
      .catch(() => {
        if (!controller.signal.aborted) setConnection("Local connection unavailable.");
      });
    return () => controller.abort();
  }, []);
  return (
    <Page title="Easy Property Management">
      <p role="status">{connection}</p>
      <p>The application interface is being prepared. Property workflows are not available yet.</p>
    </Page>
  );
}

const root = document.getElementById("root");
if (!root) throw new Error("The application root is missing.");
createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
