import { useState, type ReactNode } from "react";
import { DisclosureList, DisclosureRow } from "./disclosure";

/** Source adapters supply authoritative display facts and actions. No queue
 * classification or date conversion belongs in these presentation components. */
export interface AttentionItem {
  sourceKey: string;
  title: string;
  summary: string;
  status: string;
  renderDetails: (visible: boolean) => ReactNode;
}

export function AttentionSection({
  title,
  items,
  total,
  asOf,
  emptyMessage,
}: {
  title: string;
  items: readonly AttentionItem[];
  total: number;
  asOf: string;
  emptyMessage: string;
}) {
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set());
  return (
    <section aria-label={title}>
      <h4>
        {title} · {total}
      </h4>
      <p>As of {asOf}</p>
      {items.length === 0 ? (
        <p>{emptyMessage}</p>
      ) : (
        <DisclosureList>
          {items.map((item) => (
            <DisclosureRow
              key={item.sourceKey}
              title={item.title}
              summary={item.summary}
              status={item.status}
              open={expanded.has(item.sourceKey)}
              onOpenChange={(open) => {
                setExpanded((current) => {
                  const next = new Set(current);
                  if (open) next.add(item.sourceKey);
                  else next.delete(item.sourceKey);
                  return next;
                });
              }}
            >
              {item.renderDetails}
            </DisclosureRow>
          ))}
        </DisclosureList>
      )}
      {total > items.length && (
        <p>
          Showing {items.length} of {total}. Open the source directory for more.
        </p>
      )}
    </section>
  );
}

export interface CalendarItem extends AttentionItem {
  when: { kind: "all_day"; date: string } | { kind: "timed"; instant: string; timeZone: string };
}

export function AttentionQueue({
  kind,
  ...props
}: Omit<Parameters<typeof AttentionSection>[0], "title"> & {
  kind: "needs_action" | "waiting" | "upcoming" | "information_review";
}) {
  const titles = {
    needs_action: "Needs action",
    waiting: "Waiting",
    upcoming: "Upcoming",
    information_review: "Information review",
  };
  return <AttentionSection {...props} title={titles[kind]} />;
}

export function CalendarSection({
  items,
  total,
  asOf,
}: {
  items: readonly CalendarItem[];
  total: number;
  asOf: string;
}) {
  return (
    <AttentionSection
      title="Calendar and appointments"
      asOf={asOf}
      total={total}
      emptyMessage="No recorded calendar items in this source response."
      items={items.map((item) => ({
        ...item,
        summary: `${item.when.kind === "all_day" ? `${item.when.date} · All day` : `${item.when.instant} · ${item.when.timeZone}`} · ${item.summary}`,
      }))}
    />
  );
}
