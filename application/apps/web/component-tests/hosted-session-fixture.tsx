import { createRoot } from "react-dom/client";
import { HostedSessionGate } from "../src/app/hosted-session";
import { api } from "@epm/contracts";
import "../src/style.css";

createRoot(document.getElementById("root")!).render(
  <HostedSessionGate>
    <main>
      <h1>Private workspace</h1>
      <label htmlFor="private-note">Unsubmitted note</label>
      <input id="private-note" defaultValue="" />
      <button onClick={() => void api.GET("/api/operator/bootstrap")}>
        Check protected record
      </button>
    </main>
  </HostedSessionGate>,
);
