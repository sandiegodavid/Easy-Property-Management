import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider, Link } from "react-router-dom";
import { WorkspaceGate } from "../src/app/workspace-gate";
import { useRecoverableForm, RecoveryNavigation } from "../src/shared/use-recoverable-form";
import { setup } from "./recovery-fixture";
import "../src/style.css";

const item = await setup();
const project = (values: { title: string }) => ({
  expectedRevision: item.task.revision,
  changes: { title: values.title },
});
function Form() {
  const { form, controller, state, blocker } = useRecoverableForm({
    id: item.id,
    identity: item.identity,
    initial: { title: "Unfinished title" },
    project,
  });
  return (
    <>
      <label htmlFor="title">Title</label>
      <input id="title" {...form.register("title")} />
      <p role="status">{state.draft}</p>
      {state.error && <p role="alert">{state.error}</p>}
      <Link to="/done">Leave form</Link>
      <RecoveryNavigation controller={controller} blocker={blocker} />
    </>
  );
}
const router = createBrowserRouter([
  { path: "/component-tests/recovery-form.html", element: <Form /> },
  { path: "/done", element: <p>Navigation completed</p> },
]);
const root = document.getElementById("root");
if (root)
  createRoot(root).render(
    <WorkspaceGate>
      <RouterProvider router={router} />
    </WorkspaceGate>,
  );
