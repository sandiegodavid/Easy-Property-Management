import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { WorkspaceGate } from "./app/workspace-gate";
import { ApplicationShell } from "./app/shell";
import "./style.css";

const root = document.getElementById("root");
if (!root) throw new Error("The application root is missing.");
document.documentElement.dataset.theme = window.matchMedia("(prefers-color-scheme: dark)").matches
  ? "dark"
  : "light";
createRoot(root).render(
  <StrictMode>
    <WorkspaceGate>
      <ApplicationShell />
    </WorkspaceGate>
  </StrictMode>,
);
