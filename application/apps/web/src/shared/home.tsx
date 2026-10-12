import { Link } from "react-router-dom";
import { AsyncRegion } from "@epm/ui";

export function Home() {
  return (
    <section aria-label="Home">
      <h2>Home</h2>
      <AsyncRegion
        title="Home attention and calendar"
        state={{
          kind: "unavailable",
          message:
            "The combined Home work queue and calendar are not available yet. Open a source workflow to review its current records.",
        }}
      />
      <p>Hiding a destination does not hide its obligations.</p>
      <nav aria-label="Task attention">
        <Link to="/tasks">Task deadlines and reminders</Link>{" "}
        <Link to="/tasks?followUps=true">Waiting and follow-ups</Link>
      </nav>
      <p>Review information coverage in the relevant Property or Owner workspace.</p>
    </section>
  );
}
