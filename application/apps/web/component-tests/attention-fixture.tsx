import { createRoot } from "react-dom/client";
import { useState } from "react";
import { AttentionQueue, CalendarSection, type AttentionItem, type CalendarItem } from "@epm/ui";
import "../src/style.css";

const asOf = "2026-10-12T12:00:00Z";
const item: AttentionItem = {
  sourceKey: "task:fixture",
  title: "Review repair appointment",
  summary: "Urgent · Original deadline overdue",
  status: "Waiting for contractor · Follow-up not scheduled",
  renderDetails: () => (
    <label>
      Follow-up note
      <input defaultValue="" />
    </label>
  ),
};
const appointments: CalendarItem[] = [
  {
    ...item,
    sourceKey: "appointment:all-day",
    title: "All-day visit",
    when: { kind: "all_day", date: "2026-10-13" },
  },
  {
    ...item,
    sourceKey: "appointment:timed",
    title: "Timed visit",
    when: { kind: "timed", instant: "2026-10-13T17:00:00Z", timeZone: "America/Los_Angeles" },
  },
];
function Fixture() {
  const [dark, setDark] = useState(false);
  return (
    <main>
      <button
        onClick={() => {
          setDark(!dark);
          document.documentElement.dataset.theme = dark ? "light" : "dark";
        }}
      >
        Switch theme
      </button>
      {(["needs_action", "waiting", "upcoming", "information_review"] as const).map((kind) => (
        <AttentionQueue
          key={kind}
          kind={kind}
          items={[item]}
          total={3}
          asOf={asOf}
          emptyMessage="No source items"
        />
      ))}
      <CalendarSection items={appointments} total={2} asOf={asOf} />
    </main>
  );
}
createRoot(document.getElementById("root")!).render(<Fixture />);
