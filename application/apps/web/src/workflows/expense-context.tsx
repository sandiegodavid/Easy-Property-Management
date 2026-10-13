import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@epm/contracts";
import type { components } from "@epm/contracts/generated";
import { scalar, workflows } from "@epm/contracts/workflows";
import { useWorkspace } from "../app/workspace-gate";
import { Link, useSearchParams } from "react-router-dom";
import { CommandLoader } from "./command";
import { readResult } from "./reads";
import { moneyRecordUrl } from "./money-records";

export function ExpenseContext({
  values,
  locked,
  onChange,
  candidates,
}: {
  values: Record<string, unknown>;
  locked: boolean;
  onChange: (values: Record<string, unknown>) => void;
  candidates: components["schemas"]["ExpenseDuplicateCandidate"][];
}) {
  const { scope } = useWorkspace();
  const [cursor, setCursor] = useState<string>();
  const [providerSearch, setProviderSearch] = useState("");
  const [search, setSearch] = useState<string>();
  const [providerCursor, setProviderCursor] = useState<string>();
  const historical =
    values.historicalEntryConfirmed === true && !!scalar(values.historicalEntryReason, "").trim();
  const propertyId = scalar(values.propertyId, "");
  const properties = useQuery({
    queryKey: scope.key("expense-property-choices", historical, cursor),
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/properties", {
          signal,
          params: { query: { status: historical ? undefined : "active", pageSize: 25, cursor } },
        }),
      ),
  });
  const property = useQuery({
    queryKey: scope.key("expense-selected-property", propertyId),
    enabled: /^[0-9a-f-]{36}$/.test(propertyId),
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/properties/{property_id}", {
          signal,
          params: { path: { property_id: propertyId } },
        }),
      ),
  });
  const providers = useQuery({
    queryKey: scope.key("expense-provider-search", search, historical, providerCursor),
    enabled: search !== undefined,
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/providers", {
          signal,
          params: {
            query: {
              search,
              archiveState: historical ? "all" : "active",
              limit: 25,
              cursor: providerCursor,
            },
          },
        }),
      ),
  });
  return (
    <section aria-label="Expense context">
      <h3>Review where and to whom money was paid</h3>
      <p>This records an already-paid expense. Estimates and unpaid bills do not belong here.</p>
      {candidates.length > 0 && (
        <section aria-label="Possible duplicate expenses">
          <h3>Review possible duplicate expenses</h3>
          {candidates.map((item) => (
            <p key={item.id}>
              {item.paidOn} · {item.amount} USD · {item.payeeName} · {item.description}{" "}
              <Link to={moneyRecordUrl("expense", item.id)}>Open existing expense</Link>
            </p>
          ))}
          <Link to="/money">Go back</Link>{" "}
          <button
            type="button"
            disabled={locked}
            onClick={() => onChange({ ...values, duplicateConfirmed: true })}
          >
            Record separately
          </button>
          {values.duplicateConfirmed === true && (
            <p>Confirmed as a separate payment. Review and save.</p>
          )}
        </section>
      )}
      <label>
        Select Property
        <select
          disabled={locked}
          value={properties.data?.items.some((item) => item.id === propertyId) ? propertyId : ""}
          onChange={(event) =>
            onChange({ ...values, propertyId: event.target.value, spaceId: undefined })
          }
        >
          <option value="">Choose a Property on this page</option>
          {properties.data?.items.map((item) => (
            <option key={item.id} value={item.id}>
              {item.displayName}
              {item.status === "archived" ? " · Archived" : ""}
            </option>
          ))}
        </select>
      </label>
      {properties.error && (
        <p role="alert">Property choices unavailable: {properties.error.message}</p>
      )}
      {properties.data?.nextCursor && (
        <button
          type="button"
          disabled={locked}
          onClick={() => setCursor(properties.data?.nextCursor ?? undefined)}
        >
          Next Property choices
        </button>
      )}
      {cursor && (
        <button type="button" disabled={locked} onClick={() => setCursor(undefined)}>
          First Property choices
        </button>
      )}
      {property.error && <p role="alert">Property context unavailable: {property.error.message}</p>}
      {property.data && (
        <>
          <p>
            {property.data.displayName} · Property local time zone: {property.data.timeZone}
          </p>
          <label>
            Space within selected Property
            <select
              disabled={locked}
              value={scalar(values.spaceId, "")}
              onChange={(event) =>
                onChange({ ...values, spaceId: event.target.value || undefined })
              }
            >
              <option value="">Whole Property</option>
              {property.data.spaces
                .filter((space) => historical || !space.archivedAt)
                .map((space) => (
                  <option key={space.id} value={space.id}>
                    {space.displayName}
                    {space.archivedAt ? " · Archived" : ""}
                  </option>
                ))}
            </select>
          </label>
          {(property.data.archivedAt ||
            property.data.spaces.some(
              (space) => space.id === values.spaceId && space.archivedAt,
            )) && (
            <p role="alert">
              Archived historical selection: confirm the historical entry and record its reason
              before saving.
            </p>
          )}
        </>
      )}
      <fieldset disabled={locked}>
        <legend>Payee choice</legend>
        <label>
          Provider search
          <input
            maxLength={240}
            value={providerSearch}
            onChange={(event) => setProviderSearch(event.target.value)}
          />
        </label>
        <button
          type="button"
          onClick={() => {
            setSearch(providerSearch);
            setProviderCursor(undefined);
          }}
        >
          Search saved Providers
        </button>
        {providers.error && (
          <p role="alert">Provider search unavailable: {providers.error.message}</p>
        )}
        {providers.data?.items.map((item) => (
          <p key={item.party.id}>
            {item.party.displayName} · {item.profile.selectionStatus}{" "}
            {item.profile.archivedAt && "· Archived historical selection"}{" "}
            <button
              type="button"
              onClick={() =>
                onChange({ ...values, providerPartyId: item.party.id, payeeName: undefined })
              }
            >
              Use Provider {item.party.displayName}
            </button>
          </p>
        ))}
        {providers.data?.nextCursor && (
          <button
            type="button"
            onClick={() => setProviderCursor(providers.data?.nextCursor ?? undefined)}
          >
            Next Provider choices
          </button>
        )}
        <button
          type="button"
          onClick={() => onChange({ ...values, providerPartyId: undefined, payeeName: "" })}
        >
          Use a merchant label instead
        </button>
        <p>
          Use exactly one saved Provider or the merchant label field. Party-funded spending requires
          the existing payer Party ID.
        </p>
      </fieldset>
      {historical && (
        <p role="alert">
          Historical entry is exceptional. Include a reason for archived Property, Space, Provider
          or category references.
        </p>
      )}
    </section>
  );
}

export function ExpenseEvidenceArchive() {
  const [params] = useSearchParams();
  const target = params.get("target");
  const report = params.get("reportEvidence") === "true";
  const { scope } = useWorkspace();
  const result = useQuery({
    queryKey: scope.key("expense-evidence-archive-source", target, report),
    enabled: !!target,
    queryFn: async ({ signal }) => {
      const link = readResult(
        await api.GET("/api/file-links/{link_id}", {
          signal,
          params: { path: { link_id: target! } },
        }),
      );
      if (link.entityType !== (report ? "owner_rent_report" : "expense"))
        throw new Error("Select evidence from its owning money record.");
      if (report)
        readResult(
          await api.GET("/api/owner-rent-reports/{report_id}", {
            signal,
            params: { path: { report_id: link.entityId } },
          }),
        );
      else
        readResult(
          await api.GET("/api/expenses/{expense_id}", {
            signal,
            params: { path: { expense_id: link.entityId } },
          }),
        );
      return link;
    },
  });
  if (!target)
    return <p role="alert">Select an evidence association from its owning money record first.</p>;
  if (result.isPending) return <p role="status">Loading evidence association…</p>;
  if (result.error) return <p role="alert">{result.error.message}</p>;
  const link = result.data;
  return (
    <>
      {link.archivedAt && (
        <p>
          This association is already archived. Its history remains retained; reconcile the original
          attempt rather than archiving again.
        </p>
      )}
      <p>
        Archive only this evidence association. The source, file and reason remain retained. A
        verified Owner report must retain at least one available evidence link.
      </p>
      <CommandLoader
        definition={workflows.find((item) => item.formKey === "file.link.archive")!}
        sourceId={target}
        revision={link.revision}
        canSubmit={() => !link.archivedAt}
        returnTo={`/money?record=${report ? "report" : "expense"}&id=${link.entityId}`}
        reviewSource={async () => {
          const current = readResult(
            await api.GET("/api/file-links/{link_id}", { params: { path: { link_id: target } } }),
          );
          return { revision: current.revision, value: current };
        }}
      />
    </>
  );
}

export function ExpenseFilters() {
  const [params, setParams] = useSearchParams();
  const keys = [
    "spaceId",
    "categoryId",
    "providerPartyId",
    "paidByKind",
    "paidByPartyId",
    "paidFrom",
    "paidTo",
    "hasEvidence",
  ];
  return (
    <form
      className="directory-filters"
      onSubmit={(event) => {
        event.preventDefault();
        const data = new FormData(event.currentTarget);
        const next = new URLSearchParams(params);
        for (const key of keys) {
          const value = data.get(key);
          if (typeof value === "string" && value) next.set(key, value);
          else next.delete(key);
        }
        next.delete("cursor");
        setParams(next);
      }}
    >
      {[
        ["spaceId", "Space ID"],
        ["categoryId", "Category ID"],
        ["providerPartyId", "Provider Party ID"],
        ["paidByPartyId", "Payer Party ID"],
      ].map(([key, label]) => (
        <label key={key}>
          {label}
          <input name={key} maxLength={36} defaultValue={params.get(key) ?? ""} />
        </label>
      ))}
      <label>
        Paid by
        <select name="paidByKind" defaultValue={params.get("paidByKind") ?? ""}>
          <option value="">Any</option>
          <option value="local_operator">Local operator</option>
          <option value="party">Party</option>
        </select>
      </label>
      <label>
        Date paid from
        <input type="date" name="paidFrom" defaultValue={params.get("paidFrom") ?? ""} />
      </label>
      <label>
        Date paid to
        <input type="date" name="paidTo" defaultValue={params.get("paidTo") ?? ""} />
      </label>
      <label>
        Evidence
        <select name="hasEvidence" defaultValue={params.get("hasEvidence") ?? ""}>
          <option value="">Any</option>
          <option value="true">Has active evidence</option>
          <option value="false">No active evidence</option>
        </select>
      </label>
      <button>Apply Expense filters</button>
    </form>
  );
}
