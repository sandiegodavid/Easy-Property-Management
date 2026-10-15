import type { components } from "@epm/contracts/generated";
import { HomeSourceLink } from "./home-navigation";
import { formatHomeTemporal } from "./home-time";

type Schema = components["schemas"];
type Source = Schema["SourceTarget"]["source"];
type Item = Schema["HomeItem"];
const words = (value: string) => value.replaceAll("_", " ");

// Navigation adapters only. The owning page reloads current facts and decides
// which commands are allowed; a Home capture never authorizes a mutation.
const actions = {
  review_task: "View",
  record_payment: "Record payment",
  review_issue: "Review issue",
  review_report: "Review report",
  review_concern: "Review concern",
  review_lease: "Review lease",
  review_appointment: "View",
  review_coverage: "Review coverage",
} satisfies Record<Item["nextAction"]["kind"], string>;

export function homeActionLabel(item: Item) {
  return actions[item.nextAction.kind];
}

export function homeSourceUrl(source: Source): string | null {
  const id = encodeURIComponent(source.id);
  switch (source.kind) {
    case "task":
      return `/tasks?record=task&id=${id}`;
    case "maintenance_issue":
      return `/maintenance?record=issue&id=${id}`;
    case "owner_concern":
      return `/maintenance?record=concern&id=${id}`;
    case "owner_rent_report":
      return `/money?record=report&id=${id}`;
    case "rent_expectation":
      return `/money?record=expectation&id=${id}`;
    case "lease":
      return `/leases/${id}`;
    case "coverage":
      return `/coverage/${source.subjectKind}/${id}/${source.area}`;
    case "maintenance_appointment":
      return null; // Requires the explicit owning issue, never a guessed parent.
  }
}

function ChildActions({ child }: { child: Schema["ChildPreview"] }) {
  const url = homeSourceUrl(child.target.source);
  return (
    <li>
      {words(child.kind)} · {words(child.sourceStatus ?? "state at capture")}
      <ul>
        {child.reasons.map((reason, index) => (
          <li key={index}>
            {words(reason.code)}
            {reason.at || reason.on ? ` · ${formatHomeTemporal(reason)}` : ""}
          </li>
        ))}
      </ul>
      {url && (
        <HomeSourceLink to={child.kind === "reminder" ? `${url}#task-reminders` : url}>
          {child.kind === "reminder"
            ? "Review reminder and actions"
            : "Review linked Task and actions"}
        </HomeSourceLink>
      )}
      {child.childCount > 0 && (
        <p>
          {child.childCount} reminders; {child.children.length} shown at capture. Open the Task for
          current reminders.
        </p>
      )}
      {child.children.length > 0 && (
        <ul>
          {child.children.map((reminder) => (
            <ChildActions key={reminder.id} child={reminder} />
          ))}
        </ul>
      )}
    </li>
  );
}

export function HomeSourceActions({ item }: { item: Item }) {
  const source = item.nextAction.target.source;
  const url =
    source.kind === "maintenance_appointment"
      ? item.relatedSource?.source.kind === "maintenance_issue"
        ? `${homeSourceUrl(item.relatedSource.source)}#appointment-${source.id}`
        : null
      : homeSourceUrl(source);
  const tasks =
    item.source.kind === "maintenance_issue" || item.source.kind === "owner_concern"
      ? `/tasks?entityType=${item.source.kind}&entityId=${encodeURIComponent(item.source.id)}`
      : null;
  return (
    <section aria-label="Source workflow and grouped actions">
      <p>
        {words(item.provenance.owner)} · Source revision {item.sourceRevision}. Status and dates
        above are from this capture. Open the owning workflow for current context, evidence and
        permitted actions. No lifecycle change is made by expanding this row.
      </p>
      {item.relatedSource && (
        <p>
          Related {words(item.relatedSource.source.kind)} is{" "}
          {item.relatedSource.active ? "active" : "terminal"} at capture. Task and reminder outcomes
          do not change that source.
        </p>
      )}
      {item.outstandingMinor != null && (
        <p>
          Recorded outstanding: {item.currency} {(item.outstandingMinor / 100).toFixed(2)} at
          capture; review current allocations before recording payment.
        </p>
      )}
      {url ? (
        <>
          <p>
            <HomeSourceLink to={url}>{actions[item.nextAction.kind]}</HomeSourceLink>
          </p>
          <HomeSourceLink to={url}>View {words(item.source.kind)} details</HomeSourceLink>
        </>
      ) : (
        <p>Source detail context is unavailable.</p>
      )}
      {item.childCount > 0 && (
        <>
          <p>
            {item.childCount} linked Task/reminder records; {item.children.length} shown in this
            preview. These are independently actionable in their owning workflows.
          </p>
          <ul>
            {item.children.map((child) => (
              <ChildActions key={child.id} child={child} />
            ))}
          </ul>
          {tasks ? (
            <HomeSourceLink to={tasks}>Review all linked Tasks and their reminders</HomeSourceLink>
          ) : url ? (
            <HomeSourceLink to={`${url}#task-reminders`}>
              Review all current reminders
            </HomeSourceLink>
          ) : null}
        </>
      )}
    </section>
  );
}
