import { DynamicFilterForm } from "../shared/dynamic-filter-form";
import { useQuery } from "@tanstack/react-query";
import { PageAsOf } from "../shared/page-as-of";
import { useLocation, useSearchParams } from "react-router-dom";
import { SourceWorkflowLink as Link } from "../shared/home-navigation";
import { api } from "@epm/contracts";
import type { components } from "@epm/contracts/generated";
import { record, scalar } from "@epm/contracts/workflows";
import { useWorkspace } from "../app/workspace-gate";
import { readResult } from "./reads";
import { MoneyFacts, moneyRecordUrl } from "./money-records";
import { MoneyScope } from "./money";

type Metric = components["schemas"]["Metric"];
export function MoneyReporting() {
  const { scope } = useWorkspace();
  const location = useLocation();
  const navigationState: unknown = location.state;
  const [params, setParams] = useSearchParams();
  const fromOn = params.get("fromOn") ?? "",
    throughOn = params.get("throughOn") ?? "";
  const propertyId = params.get("propertyId") ?? undefined,
    ownerId = params.get("ownerId");
  const metric = params.get("metric") as Metric | null,
    cursor = params.get("cursor") ?? undefined;
  const sourceRevision = params.get("sourceRevision") ?? undefined;
  const propertyState =
    (["active", "archived", "all"] as const).find((item) => item === params.get("propertyState")) ??
    "all";
  const query = {
    fromOn,
    throughOn,
    propertyState,
    propertyIds: propertyId ? [propertyId] : [],
    pageSize: 25,
    cursor,
    sourceRevision,
  };
  const enabled = !!fromOn && !!throughOn && (!ownerId || !!propertyId) && !params.has("leaseId");
  const properties = useQuery({
    queryKey: scope.key("money-reporting", params.toString()),
    enabled: enabled && !metric,
    retry: false,
    queryFn: async ({ signal }) =>
      readResult(await api.GET("/api/money/properties", { signal, params: { query } })),
  });
  const sources = useQuery({
    queryKey: scope.key("money-contributions", params.toString()),
    enabled: enabled && !!metric && metric !== "recordedDepositObligation",
    retry: false,
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/money/sources", {
          signal,
          params: { query: { ...query, metric: metric! } },
        }),
      ),
  });
  const accounts = useQuery({
    queryKey: scope.key("money-obligations", params.toString()),
    enabled: enabled && metric === "recordedDepositObligation",
    retry: false,
    queryFn: async ({ signal }) =>
      readResult(await api.GET("/api/money/deposit-accounts", { signal, params: { query } })),
  });
  const result = metric
    ? metric === "recordedDepositObligation"
      ? accounts
      : sources
    : properties;
  function nextPage(value: string) {
    const next = new URLSearchParams(params);
    next.set("cursor", value);
    const revision =
      sources.data?.sourceRevision ??
      accounts.data?.sourceRevision ??
      properties.data?.summary.sourceRevision;
    if (revision) next.set("sourceRevision", revision);
    setParams(next, { state: navigationState });
  }
  function metricTarget(value: Metric) {
    const next = new URLSearchParams(params);
    next.set("metric", value);
    next.set("sourceRevision", properties.data!.summary.sourceRevision);
    next.delete("cursor");
    return `/money?${next}`;
  }
  return (
    <section aria-label="Money reporting">
      <h3>Explicit-period recorded activity</h3>
      <MoneyScope />
      {params.has("leaseId") && (
        <p>
          Reporting describes whole Properties. Remove the Lease filter before requesting these
          totals.
        </p>
      )}
      <p>
        These totals describe recorded activity, not profit, bank balance or amounts due to owners.
        Current deposit obligation includes all recorded dates at the displayed instant.
      </p>
      {ownerId && !propertyId && (
        <p>
          Select a related Property from{" "}
          <Link to={`/owners/${ownerId}/money`}>Owner money context</Link> before requesting
          whole-property reporting.
        </p>
      )}
      <DynamicFilterForm
        onSubmit={(event) => {
          event.preventDefault();
          const data = new FormData(event.currentTarget);
          const next = new URLSearchParams(params);
          for (const key of ["fromOn", "throughOn", "propertyState"])
            next.set(key, scalar(data.get(key)));
          next.delete("cursor");
          next.delete("sourceRevision");
          next.delete("metric");
          setParams(next, { state: navigationState, replace: true, preventScrollReset: true });
        }}
      >
        <label>
          Reporting from (required)
          <input name="fromOn" type="date" required defaultValue={fromOn} />
        </label>
        <label>
          Reporting through (required)
          <input name="throughOn" type="date" required defaultValue={throughOn} />
        </label>
        <label>
          Reporting property state
          <select name="propertyState" defaultValue={propertyState}>
            <option value="all">All retained properties</option>
            <option value="active">Active</option>
            <option value="archived">Archived</option>
          </select>
        </label>
      </DynamicFilterForm>
      {!enabled && <p>Choose an explicit inclusive date range to load reporting.</p>}
      {result.isFetching && <p role="status">Loading money reporting…</p>}
      {result.error && (
        <div role="alert">
          <p>
            {result.error.message} Reporting is unavailable; amounts have not been replaced with
            zero.
          </p>
          <button
            onClick={() => {
              const next = new URLSearchParams(params);
              next.delete("cursor");
              next.delete("sourceRevision");
              next.delete("metric");
              setParams(next, { state: navigationState });
              if (!cursor && !sourceRevision && !metric) void result.refetch();
            }}
          >
            Restart reporting with these filters
          </button>
        </div>
      )}
      {properties.data && !metric && (
        <>
          <PageAsOf asOf={properties.data.summary.asOf} />
          <p>
            {properties.data.matchingTotal} matching properties · Property-local dates {fromOn}{" "}
            through {throughOn}
          </p>
          {(["operating", "depositActivity", "depositObligations"] as const).map((name) => (
            <section key={name} aria-label={name}>
              <h4>{name.replace(/([A-Z])/g, " $1")}</h4>
              {properties.data.summary[name].available ? (
                <MoneyFacts
                  value={properties.data.summary[name]}
                  fields={Object.keys(properties.data.summary[name])}
                  labels={{ operatingRemainder: "Rent less net expenses" }}
                />
              ) : (
                <p role="alert">This money section is unavailable.</p>
              )}
            </section>
          ))}
          <nav aria-label="Reporting metric sources">
            {properties.data.summary.metrics.map((item) => (
              <Link key={item.metric} to={metricTarget(item.metric)}>
                {item.metric === "operatingRemainder" ? "Rent less net expenses" : item.metric} ·
                USD {item.amount}
              </Link>
            ))}
            <Link to={metricTarget("recordedDepositObligation")}>
              Current recorded deposit obligation
            </Link>
          </nav>
          {properties.data.items.map((item) => (
            <article key={item.propertyId}>
              <Link
                to={`/money?${new URLSearchParams({ ...Object.fromEntries([...params].filter(([key]) => key !== "cursor")), propertyId: item.propertyId, sourceRevision: properties.data.summary.sourceRevision })}`}
              >
                {item.propertyName} · {item.propertyState}
              </Link>
              <p>
                <Link to={`/properties/${item.propertyId}/money`}>Property context</Link>
              </p>
              {item.operating.available ? (
                <MoneyFacts
                  value={item.operating}
                  labels={{ operatingRemainder: "Rent less net expenses" }}
                  fields={[
                    "rentReceived",
                    "expensesPaid",
                    "expenseRefundsReceived",
                    "netRecordedExpenses",
                    "operatingRemainder",
                  ]}
                />
              ) : (
                <p role="alert">Operating activity for this property is unavailable.</p>
              )}
            </article>
          ))}
        </>
      )}
      {sources.data && metric && (
        <>
          <PageAsOf asOf={sources.data.asOf} />
          <p>
            {sources.data.matchingTotal} source records · Backend total USD {sources.data.total}
          </p>
          {sources.data.items.map((item) => {
            const url =
              item.sourceKind === "rent_receipt"
                ? moneyRecordUrl("receipt", item.sourceId)
                : item.sourceKind === "expense" || item.sourceKind === "expense_refund"
                  ? moneyRecordUrl("expense", item.parentId ?? item.sourceId)
                  : item.sourceKind === "settlement_credit" ||
                      item.sourceKind === "settlement_deduction"
                    ? moneyRecordUrl("settlement", item.sourceId)
                    : item.accountId
                      ? moneyRecordUrl("deposit", item.accountId)
                      : undefined;
            return (
              <article key={`${item.sourceKind}:${item.sourceId}`}>
                <p>
                  {item.sourceKind} · {item.businessOn} · USD {item.contribution} · {item.lifecycle}
                </p>
                {url && <Link to={url}>Open contribution source</Link>}
              </article>
            );
          })}
        </>
      )}
      {accounts.data && metric === "recordedDepositObligation" && (
        <>
          <PageAsOf asOf={accounts.data.asOf} />
          <p>{accounts.data.matchingTotal} deposit accounts</p>
          <MoneyFacts value={accounts.data.totals} fields={Object.keys(accounts.data.totals)} />
          {accounts.data.items.map((item) => (
            <article key={item.accountId}>
              <Link to={moneyRecordUrl("deposit", item.accountId)}>
                Open deposit obligation source
              </Link>
              <MoneyFacts
                value={item}
                fields={[
                  "recordedDepositObligation",
                  "agreedAmount",
                  "varianceAmount",
                  "unsettledReceiptAmount",
                  "requiresReview",
                  "unresolved",
                ]}
              />
            </article>
          ))}
        </>
      )}
      {result.data &&
        Array.isArray(record(result.data).items) &&
        (record(result.data).items as unknown[]).length === 0 && (
          <p>No records in this reporting view.</p>
        )}
      {(metric
        ? (sources.data?.nextCursor ?? accounts.data?.nextCursor)
        : properties.data?.nextCursor) && (
        <button
          onClick={() =>
            nextPage(
              (metric
                ? (sources.data?.nextCursor ?? accounts.data?.nextCursor)
                : properties.data?.nextCursor)!,
            )
          }
        >
          Next reporting page
        </button>
      )}
      {metric && (
        <button
          onClick={() => {
            const next = new URLSearchParams(params);
            next.delete("metric");
            next.delete("cursor");
            next.delete("sourceRevision");
            setParams(next, { state: navigationState });
          }}
        >
          Return to reporting totals
        </button>
      )}
    </section>
  );
}
