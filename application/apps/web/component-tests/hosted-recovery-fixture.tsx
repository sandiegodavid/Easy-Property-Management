import { createRoot } from "react-dom/client";
import { HostedRecovery } from "../src/app/hosted-recovery";
import { admitHostedSession } from "../src/app/hosted-session-state";

const meta = document.createElement("meta");
meta.name = "epm-deployment";
meta.content = "hosted_managed";
document.head.appendChild(meta);

admitHostedSession("operator-csrf-token");

createRoot(document.getElementById("root")!).render(
  <main>
    <h1>Hosted Workspace</h1>
    <HostedRecovery forceVisible />
  </main>,
);
