import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "@epm/contracts";
import { record, scalar } from "@epm/contracts/workflows";
import { useWorkspace } from "../app/workspace-gate";
import { MoneyFacts } from "./money-presentation";
import { Facts, readResult } from "./reads";
import { workflowUrl } from "./command";

export function assignmentProblem(values: Record<string, unknown>) {
  if (
    !values.quoteId &&
    !(values.directAssignmentConfirmed === true && scalar(values.selectionReason, "").trim())
  )
    return "Direct assignment requires explicit confirmation and a selection reason.";
  if (
    values.replacesAssignmentId &&
    !(values.replacementConfirmed === true && scalar(values.endReason, "").trim())
  )
    return "Reassignment requires confirmation and an end reason for the current assignment.";
  return undefined;
}

export function quoteProblem(values: Record<string, unknown>) {
  const start = scalar(values.earliestWorkStartOn, ""),
    finish = scalar(values.estimatedWorkFinishOn, "");
  if (!!start !== !!finish || (start && finish < start))
    return "Quoted work dates require both earliest start and estimated finish, with finish on or after start.";
  return undefined;
}

export function QuoteCommandContext({
  values,
  source,
}: {
  values: Record<string, unknown>;
  source: Record<string, unknown>;
}) {
  const { scope } = useWorkspace();
  const id = scalar(values.providerPartyId, "");
  const provider = useQuery({
    queryKey: scope.key("quote-provider-review", id),
    enabled: !!id,
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/providers/{party_id}", { signal, params: { path: { party_id: id } } }),
      ),
  });
  const quote = (Array.isArray(source.quotes) ? source.quotes.map(record) : []).find(
    (item) => item.id === values.quoteId,
  );
  return (
    <section aria-label="Quote and Provider selection review">
      <h3>Offer and selection, not paid spending or completed work</h3>
      <p>
        Quoted totals never enter Finance totals. Paired earliest-start and estimated-finish dates
        are Provider-supplied local-date estimates, not appointments, deadlines or proof of actual
        work. Both dates are required together, with finish on or after start.
      </p>
      <p>
        Choose the exact quote, or omit it for explicitly confirmed direct assignment with a reason.
        Quote identity, Provider identity, expiry and current availability are rechecked by the
        server. No Provider is ranked, contacted or assigned automatically.
      </p>
      {provider.error && <p role="alert">Provider review unavailable: {provider.error.message}</p>}
      {provider.data && (
        <>
          <Facts value={provider.data.party} fields={["displayName", "archivedAt"]} />
          <Facts value={provider.data.profile} fields={["selectionStatus", "archivedAt"]} />
          <Link to={`/providers/${id}/details`}>Review Provider services, areas and history</Link>
          {!provider.data.profile.officialIds.length && (
            <p>
              Record an official ID on this Provider before assigning maintenance work. You may
              still record a quote.
            </p>
          )}
          {provider.data.profile.selectionStatus === "avoid" && (
            <p role="alert">
              This Provider is marked avoid. Assignment requires explicit Avoid override
              confirmation and a bounded reason; receiving a quote alone is allowed.
            </p>
          )}
        </>
      )}
      {quote && (
        <MoneyFacts
          value={quote}
          fields={[
            "providerDisplayNameSnapshot",
            "label",
            "scopeSummary",
            "amountMinor",
            "validThrough",
            "earliestWorkStartOn",
            "estimatedWorkFinishOn",
          ]}
        />
      )}
      {quote && quote.providerPartyId !== values.providerPartyId && (
        <p role="alert">
          The selected quote belongs to another Provider. Select a matching option before
          assignment.
        </p>
      )}
      {!!values.replacesAssignmentId && (
        <p>
          Reassignment atomically ends the current assignment and creates a replacement; both
          records and reasons remain retained. It does not resolve the issue or change Tasks,
          appointments, journals or expenses.
        </p>
      )}
    </section>
  );
}

export function QuoteComparison({ id, active }: { id: string; active: boolean }) {
  const { scope } = useWorkspace();
  const result = useQuery({
    queryKey: scope.key("maintenance-quote-comparison", id),
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/maintenance-issues/{issue_id}/quote-comparison", {
          signal,
          params: { path: { issue_id: id } },
        }),
      ),
  });
  return (
    <section aria-label="Quote comparison">
      <h3>Compare received offers</h3>
      <p>
        Review scope, terms, exact USD totals and quoted dates yourself. Ordering is server-owned;
        active nonexpired offers precede expired/withdrawn history. No total is summed or winner
        inferred. Assignment records preserve which exact option was selected.
      </p>
      {result.isPending && <p role="status">Loading bounded comparison…</p>}
      {result.error && <p role="alert">Comparison unavailable: {result.error.message}</p>}
      {result.data?.quotes.length === 0 && (
        <p>
          No received quotes. A direct assignment requires its own explicit confirmation and reason.
        </p>
      )}
      {result.data?.quotes.map((quote) => (
        <article key={quote.id}>
          <MoneyFacts
            value={quote}
            fields={[
              "providerDisplayNameSnapshot",
              "label",
              "scopeSummary",
              "amountMinor",
              "receivedOn",
              "validThrough",
              "earliestWorkStartOn",
              "estimatedWorkFinishOn",
              "termsNotes",
              "documentCount",
              "withdrawnAt",
              "withdrawalReason",
              "isCurrentAssignment",
              "isHistoricalAssignment",
              "currentPartyState",
              "currentProviderProfileState",
            ]}
          />
          {active && !quote.withdrawnAt && (
            <Link
              to={`${workflowUrl("maintenance.assignment.create", id)}&quoteId=${quote.id}&providerPartyId=${quote.providerPartyId}`}
            >
              Review assignment for {quote.label}
            </Link>
          )}
        </article>
      ))}
    </section>
  );
}
