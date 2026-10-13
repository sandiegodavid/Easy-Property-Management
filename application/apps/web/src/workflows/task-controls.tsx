import { useNavigate } from "react-router-dom";
import { scalar } from "@epm/contracts/workflows";
import { useWorkspace } from "../app/workspace-gate";
import { workflowUrl } from "./command";

export function TaskCompletion({ value }: { value: Record<string, unknown> }) {
  const navigate = useNavigate();
  const { scope } = useWorkspace();
  if (!["open", "in_progress"].includes(scalar(value.status))) return null;
  return (
    <>
      <label>
        <input
          type="checkbox"
          checked={false}
          disabled={!scope.canWrite}
          onChange={() => {
            void navigate(workflowUrl("task.complete", scalar(value.id)), {
              state: { returnTo: "/tasks" },
            });
          }}
        />
        Complete Task: {scalar(value.title)}
      </label>
      <p>Review and confirm completion before it is recorded.</p>
    </>
  );
}

export function TaskOutcome({ value }: { value: Record<string, unknown> }) {
  if (!["completed", "cancelled"].includes(scalar(value.status))) return null;
  return (
    <section aria-label="Task outcome history">
      <p>
        {value.status === "completed" ? "Completed at" : "Cancelled at"}:{" "}
        {scalar(value.completedAtUtc ?? value.cancelledAtUtc)}
      </p>
      <p>Outcome note: {scalar(value.outcomeNote) || "No outcome note recorded"}</p>
      <p>This retained outcome is read-only.</p>
    </section>
  );
}
