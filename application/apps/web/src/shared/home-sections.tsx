import { useState, type ReactNode } from "react";
import type { components } from "@epm/contracts/generated";
import { AsyncRegion, DisclosureList, DisclosureRow, type AsyncState } from "@epm/ui";
import type { Attention, HomeRead, HomeFilters } from "./home-transport";
import { collectionUrl, HomeSourceLink } from "./home-navigation";
import { HomeSourceActions } from "./home-source-actions";

type Schema = components["schemas"];
type Collection = Schema["AvailableCollection"] | Schema["UnavailableCollection"];
type Capture = Schema["Capture"];
type Read = Pick<
  HomeRead<unknown>,
  "kind" | "message" | "updating" | "stale" | "elapsed" | "retry"
>;
const label = (value: string) => value.replaceAll("_", " ");

function temporal(fact: Schema["TemporalFact"]) {
  if (fact.on) return `${fact.on} · All day · ${fact.timeZone}`;
  return `${new Intl.DateTimeFormat("en-US", { timeZone: fact.timeZone, dateStyle: "medium", timeStyle: "short" }).format(new Date(fact.at!))} · ${fact.timeZone} · ${fact.at}`;
}

export function HomeRegion({
  title,
  capture,
  unavailable,
  read,
  stale = false,
  children,
}: {
  title: string;
  capture?: Capture;
  unavailable?: string;
  read: Read;
  stale?: boolean;
  children?: ReactNode;
}) {
  const retry = (
    <button disabled={read.updating} onClick={read.retry}>
      Retry {title}
    </button>
  );
  const wait =
    read.elapsed >= 2
      ? `Still loading ${title} (${read.elapsed} seconds). Other destinations remain available.`
      : `Loading ${title}…`;
  let state: AsyncState;
  if (unavailable)
    state = {
      kind: "unavailable",
      message: `${title} unavailable: ${label(unavailable)}.`,
      recovery: retry,
    };
  else if (!capture)
    state =
      read.kind === "failed"
        ? { kind: "error", message: read.message ?? `${title} unavailable.`, recovery: retry }
        : { kind: "loading", message: wait };
  else if ((read.kind === "failed" && !read.updating) || stale || capture.freshness === "stale")
    state = {
      kind: "stale",
      asOf: capture.asOf,
      message:
        read.message ??
        "Updated attention is available. Showing the previous list until you choose to update it.",
      recovery: retry,
    };
  else if (read.updating)
    state = {
      kind: "refreshing",
      asOf: capture.asOf,
      message:
        read.elapsed >= 2
          ? `${wait} Showing information from ${capture.asOf}.`
          : `Updating — showing information from ${capture.asOf}.`,
    };
  else state = { kind: "success", asOf: capture.asOf };
  return (
    <div className="home-section">
      <AsyncRegion title={title} state={state}>
        <p className="ui-muted">
          {read.updating ? "Checking" : read.kind === "failed" || stale ? "Stale" : "Checked"} ·{" "}
          {capture?.readMode ?? "live"}
          {capture?.checkedAt && (
            <>
              {" "}
              · Checked at <time dateTime={capture.checkedAt}>{capture.checkedAt}</time>
            </>
          )}
        </p>
        {children}
      </AsyncRegion>
      {unavailable && capture && (
        <p className="ui-muted">
          Unavailable · {capture.readMode} · As of{" "}
          <time dateTime={capture.asOf}>{capture.asOf}</time>
          {read.updating ? " · Updating" : ""}
        </p>
      )}
      {!capture && read.kind !== "failed" && (
        <div className="home-skeleton" aria-hidden="true">
          {[1, 2, 3, 4, 5].map((id) => (
            <div key={id} />
          ))}
        </div>
      )}
    </div>
  );
}

function HomeRow({
  item,
  onDisclosureChange,
}: {
  item: Schema["HomeItem"];
  onDisclosureChange?: (open: boolean) => void;
}) {
  const [open, setOpen] = useState(false);
  const dates: [string, Schema["TemporalFact"] | null | undefined][] = [
    ["Task deadline", item.taskDeadline],
    ["Follow-up", item.followUp],
    ["Source deadline", item.sourceDeadline],
  ];
  const when = item.followUp ?? item.taskDeadline ?? item.sourceDeadline;
  return (
    <DisclosureRow
      title={
        item.source.kind === "coverage"
          ? `${item.title} — ${label(item.source.area)} information`
          : item.title
      }
      status={label(item.sourceStatus)}
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        onDisclosureChange?.(next);
      }}
      summary={`${item.propertyName ?? "Workspace-level"}${item.spaceName ? ` / ${item.spaceName}` : ""}${item.propertyArchived ? " · Archived" : ""} · ${item.reasons.map((reason) => label(reason.code)).join(", ")}${when ? ` · ${temporal(when)}` : ""}`}
    >
      {() => (
        <>
          <ul>
            {item.reasons.map((reason, index) => (
              <li key={index}>
                {label(reason.code)}
                {reason.at || reason.on ? ` · ${reason.at ?? reason.on} · ${reason.timeZone}` : ""}
              </li>
            ))}
          </ul>
          {dates.map(([title, fact]) =>
            fact ? (
              <p key={title}>
                {title}: {temporal(fact)}
              </p>
            ) : null,
          )}
          <HomeSourceActions item={item} />
        </>
      )}
    </DisclosureRow>
  );
}

export function HomeCollection({
  title,
  collection,
  read,
  assurance = false,
  urgent,
  stale = false,
  filters,
  onDisclosureChange,
}: {
  title: string;
  collection?: Collection;
  read: Read;
  assurance?: boolean;
  urgent?: number;
  stale?: boolean;
  filters?: HomeFilters;
  onDisclosureChange?: (open: boolean) => void;
}) {
  return (
    <HomeRegion
      title={title}
      capture={collection?.capture}
      read={read}
      stale={stale}
      unavailable={collection?.status === "unavailable" ? collection.reasonCode : undefined}
    >
      {collection?.status === "available" && (
        <>
          <h4>{collection.matchingTotal} recorded items</h4>
          {filters && (
            <HomeSourceLink to={collectionUrl(collection, filters)}>
              View all {title} ({collection.matchingTotal})
            </HomeSourceLink>
          )}
          {urgent !== undefined && urgent > 0 && <p>{urgent} urgent items in this response.</p>}
          {collection.items.length === 0 ? (
            <p>
              {assurance
                ? "No immediate actions in recorded information."
                : "No matching items in this displayed response."}
            </p>
          ) : (
            <DisclosureList>
              {collection.items.map((item) => (
                <HomeRow key={item.key} item={item} onDisclosureChange={onDisclosureChange} />
              ))}
            </DisclosureList>
          )}
          {collection.matchingTotal > collection.items.length && (
            <p>
              Showing {collection.items.length} of {collection.matchingTotal}. Open the source
              workflows to review more records.
            </p>
          )}
        </>
      )}
    </HomeRegion>
  );
}

export function LiveAttention({
  read,
  fallback,
  filters,
}: {
  read: HomeRead<Attention>;
  fallback?: Collection;
  filters?: HomeFilters;
}) {
  const [shown, setShown] = useState(read.value);
  const [pending, setPending] = useState<Attention>();
  const [openRows, setOpenRows] = useState(0);
  const next = read.value;
  if (next && shown !== next) {
    let hold = false;
    if (shown?.needsAction.status === "available" && next.needsAction.status === "available") {
      const previous = shown.needsAction;
      const current = next.needsAction;
      const previousKeys = new Set(previous.items.map((item) => item.key));
      const hasNewPreview = current.items.some((item) => !previousKeys.has(item.key));
      const membershipChanged =
        previous.matchingTotal !== current.matchingTotal ||
        hasNewPreview ||
        previous.items.some(
          (item) => !current.items.some((currentItem) => currentItem.key === item.key),
        );
      // A refreshed collection is admitted as one response. Hold it only when
      // it would replace an expanded disclosure, or when it contains newly
      // qualifying work that should be announced before replacement.
      hold =
        hasNewPreview ||
        current.matchingTotal > previous.matchingTotal ||
        (membershipChanged && openRows > 0);
    }
    if (hold) {
      if (pending !== next) setPending(next);
    } else {
      setShown(next);
      if (pending) setPending(undefined);
    }
  }

  const staged = pending ?? (shown !== next && next ? next : undefined);
  const added = !!pending;
  const unavailable = next?.needsAction.status === "unavailable";
  const collection = unavailable ? next.needsAction : (shown?.needsAction ?? fallback);
  const checked =
    !!next &&
    shown === next &&
    read.kind === "available" &&
    !read.updating &&
    !read.stale &&
    !added;
  return (
    <>
      {added && (
        <div className="ui-notice ui-warning" role="status">
          <p>
            New items need attention ·{" "}
            {staged?.needsAction.status === "available"
              ? staged.needsAction.matchingTotal
              : "Unavailable"}{" "}
            items in the latest response.
          </p>
          {openRows > 0 && <p>Expanded details stay open until you show the updated list.</p>}
          <button
            onClick={() => {
              if (!pending) return;
              setShown(pending);
              setPending(undefined);
            }}
          >
            Show updated list
          </button>
        </div>
      )}
      <HomeCollection
        title="Needs action"
        filters={filters}
        read={read}
        collection={collection}
        stale={added}
        onDisclosureChange={(open) => setOpenRows((count) => Math.max(0, count + (open ? 1 : -1)))}
        assurance={
          checked &&
          next.needsAction.status === "available" &&
          next.needsAction.capture.freshness === "checked" &&
          next.needsAction.matchingTotal === 0
        }
        urgent={shown?.priorityTotals?.urgent}
      />
      {next && (
        <p className="ui-muted">
          Live attention capture: {next.asOf}. Other sections retain their own capture times.
        </p>
      )}
    </>
  );
}

const metrics = {
  rentReceived: "Rent received",
  expensesPaid: "Expenses paid",
  expenseRefundsReceived: "Expense refunds received",
  netRecordedExpenses: "Net recorded expenses",
  operatingRemainder: "Rent less net expenses",
};
export function HomeSummaries({ value, read }: { value?: Schema["HomeResponse"]; read: Read }) {
  const money = value?.money,
    inventory = value?.inventory;
  return (
    <div className="home-supporting">
      <HomeRegion
        title="Recorded money"
        read={read}
        capture={money?.capture}
        unavailable={money?.status === "unavailable" ? money.reasonCode : undefined}
      >
        {money?.status === "available" && (
          <>
            <p>
              {money.fromOn} through {money.throughOn} · Recorded activity includes
              archived-property history and may include future-dated entries.
            </p>
            <dl>
              {money.metrics.map((metric) => (
                <div key={metric.target.metric}>
                  <dt>{metrics[metric.target.metric]}</dt>
                  <dd>
                    <HomeSourceLink
                      to={`/money?${new URLSearchParams({ tab: "reporting", metric: metric.target.metric, fromOn: metric.target.fromOn, throughOn: metric.target.throughOn, propertyState: metric.target.propertyState, sourceRevision: money.capture.sourceRevision, ...(metric.target.scope.propertyId ? { propertyId: metric.target.scope.propertyId } : {}) })}`}
                    >
                      USD {metric.amount} — View {metrics[metric.target.metric]} sources
                    </HomeSourceLink>
                  </dd>
                </div>
              ))}
            </dl>
            <p>These totals do not establish profit or owner entitlement.</p>
          </>
        )}
      </HomeRegion>
      <HomeRegion
        title="Inventory"
        read={read}
        capture={inventory?.capture}
        unavailable={inventory?.status === "unavailable" ? inventory.reasonCode : undefined}
      >
        {inventory?.status === "available" && (
          <>
            <p>Active properties only.</p>
            <dl>
              <div>
                <dt>Vacant spaces</dt>
                <dd>
                  <HomeSourceLink to={inventoryUrl(inventory.vacant)}>
                    {inventory.vacant.count} — View vacant spaces
                  </HomeSourceLink>
                </dd>
              </div>
              <div>
                <dt>Unknown occupancy</dt>
                <dd>
                  <HomeSourceLink to={inventoryUrl(inventory.unknown)}>
                    {inventory.unknown.count} — View unknown occupancy
                  </HomeSourceLink>
                </dd>
              </div>
            </dl>
          </>
        )}
      </HomeRegion>
    </div>
  );
}

function inventoryUrl(count: Schema["InventoryCount"]) {
  return `/home/inventory?${new URLSearchParams({ occupancy: count.target.occupancy, ...(count.target.scope.propertyId ? { propertyId: count.target.scope.propertyId } : {}), ...(count.viewAllCursor ? { cursor: count.viewAllCursor } : {}) })}`;
}
