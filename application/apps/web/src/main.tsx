import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { WorkspaceGate, useWorkspace } from "./app/workspace-gate";
import "./style.css";

function App() {
  const { bootstrap, scope } = useWorkspace();
  return (
    <>
      <p role="status">Local workspace connected.</p>
      {!scope.canWrite && <p>Workspace writes are unavailable.</p>}
      {(bootstrap.preferencesState !== "available" || !bootstrap.preferences) && (
        <p>Appearance and navigation preferences are unavailable. Using display defaults.</p>
      )}
      <p>The application interface is being prepared. Property workflows are not available yet.</p>
    </>
  );
}

const root = document.getElementById("root");
if (!root) throw new Error("The application root is missing.");
createRoot(root).render(
  <StrictMode>
    <WorkspaceGate>
      <App />
    </WorkspaceGate>
  </StrictMode>,
);
