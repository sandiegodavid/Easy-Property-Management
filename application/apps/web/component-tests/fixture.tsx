import { StrictMode, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  AsyncRegion,
  ConfirmDialog,
  DataTable,
  DirectoryPage,
  DisclosureList,
  DisclosureRow,
  DraftStatus,
  ErrorSummary,
  TextField,
  Toast,
  type AsyncState,
} from "@epm/ui";
import "../src/style.css";

function Fixture() {
  const [open, setOpen] = useState(false);
  const [dialog, setDialog] = useState(false);
  const [pending, setPending] = useState(false);
  const [result, setResult] = useState("");
  const [state, setState] = useState<AsyncState>({ kind: "success", asOf: "2026-10-10T12:00:00Z" });
  const [cursor, setCursor] = useState<string | null>("opaque-next");
  return (
    <main>
      <h1>Shared components</h1>
      <button
        onClick={() => {
          document.documentElement.dataset.theme =
            document.documentElement.dataset.theme === "dark" ? "light" : "dark";
        }}
      >
        Switch theme
      </button>
      <DisclosureList>
        <DisclosureRow
          title="Example record"
          summary="Display-only summary"
          status="Review needed"
          open={open}
          onOpenChange={setOpen}
        >
          {(visible) => (
            <>
              <p>Detail polling: {visible ? "active" : "paused"}</p>
              <TextField id="note" label="Note" />
              <button onClick={() => setOpen(false)}>Close details</button>
              <button onClick={() => setDialog(true)}>Archive example</button>
            </>
          )}
        </DisclosureRow>
        <DisclosureRow title="Example record" open={false} onOpenChange={() => {}}>
          {() => <p>Other list instance</p>}
        </DisclosureRow>
      </DisclosureList>
      <ErrorSummary errors={[{ fieldId: "required-name", message: "Enter a name" }]} />
      <TextField
        id="required-name"
        label="Name"
        required
        hint="Use a recognizable name"
        error="Enter a name"
      />
      <div className="ui-actions">
        {(
          ["loading", "empty", "error", "unavailable", "stale", "partial", "refreshing"] as const
        ).map((kind) => (
          <button
            key={kind}
            onClick={() =>
              setState({ kind, message: `${kind} result`, asOf: "2026-10-10T12:00:00Z" })
            }
          >
            {kind}
          </button>
        ))}
      </div>
      <AsyncRegion title="Independent section" state={{ kind: "success" }}>
        <p>Healthy section data</p>
      </AsyncRegion>
      <DirectoryPage
        title="Records"
        total={state.kind === "empty" ? 0 : null}
        state={state}
        nextCursor={cursor}
        onContinue={() => setCursor(null)}
      >
        <DataTable
          caption="Recorded amounts (USD)"
          rows={[{ id: "a", name: "Example", value: null }]}
          rowKey={(row) => row.id}
          rowLabel={(row) => row.name}
          columns={[
            { key: "amount", label: "Amount (USD)", numeric: true, value: (row) => row.value },
          ]}
        />
      </DirectoryPage>
      <DraftStatus state={{ kind: "dirty" }} />
      <Toast message={result} />
      <ConfirmDialog
        open={dialog}
        title="Archive Example record?"
        consequence={<p>This removes the record from active lists.</p>}
        confirmLabel="Confirm archive"
        pending={pending}
        onCancel={() => setDialog(false)}
        onConfirm={() => {
          setPending(true);
          window.setTimeout(() => {
            setResult("Example archived");
            setDialog(false);
            setPending(false);
          }, 150);
        }}
      />
    </main>
  );
}
const root = document.getElementById("root");
if (!root) throw new Error("Fixture root missing");
createRoot(root).render(
  <StrictMode>
    <Fixture />
  </StrictMode>,
);
