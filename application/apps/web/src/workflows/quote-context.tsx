import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { SourceWorkflowLink as Link } from "../shared/home-navigation";
import { api } from "@epm/contracts";
import { record, scalar } from "@epm/contracts/workflows";
import { useWorkspace } from "../app/workspace-gate";
import { cents, MoneyFacts } from "./money-presentation";
import { Facts, readResult } from "./reads";
import { CommandLinks, workflowUrl } from "./command";
import { formatHomeTime } from "../shared/home-time";
import { formatUsd } from "../shared/presentation";

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
          Reassignment ends the current assignment and creates a replacement; both records and
          reasons remain retained. It does not resolve the issue or change Tasks, appointments,
          journals or expenses.
        </p>
      )}
    </section>
  );
}

export function QuoteComparison({
  id,
  active,
  documents,
}: {
  id: string;
  active: boolean;
  documents: (quoteId: string) => ReactNode;
}) {
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
    <section aria-label="Quote comparison" className="issue-detail-section maintenance-quotes">
      <h3>Provider quotes</h3>
      <p>
        Compare scope, price and estimated work dates. Quotes are offers, not paid expenses. No
        provider is selected automatically.
      </p>
      {result.isPending && <p role="status">Loading bounded comparison…</p>}
      {result.error && <p role="alert">Comparison unavailable: {result.error.message}</p>}
      {result.data?.quotes.length === 0 && (
        <p>
          No received quotes. A direct assignment requires its own explicit confirmation and reason.
        </p>
      )}
      {!!result.data?.quotes.length && (
        <div
          className="maintenance-quote-scroll"
          role="region"
          aria-label="Provider quote comparison table"
        >
          <table className="maintenance-quote-table">
            <caption>Received quotes — compare each offer before assigning work</caption>
            <thead>
              <tr>
                {[
                  "Provider / quote",
                  "Work included",
                  "Quoted total",
                  "Work dates and terms",
                  "Status and actions",
                ].map((heading) => (
                  <th scope="col" key={heading}>
                    {heading}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {result.data.quotes.map((quote) => (
                <tr key={quote.id}>
                  <th scope="row">
                    <Link to={`/providers/${quote.providerPartyId}/details`}>
                      {quote.providerDisplayNameSnapshot}
                    </Link>
                    <span className="quote-secondary">{quote.label}</span>
                    {(quote.currentPartyState === "archived" ||
                      quote.currentProviderProfileState === "archived") && (
                      <span className="quote-secondary">Provider archived</span>
                    )}
                  </th>
                  <td>{quote.scopeSummary}</td>
                  <td className="quote-total">{formatUsd(cents(quote.amountMinor))}</td>
                  <td>
                    {quote.earliestWorkStartOn && quote.estimatedWorkFinishOn ? (
                      <p>
                        <strong>Estimated work:</strong> {quote.earliestWorkStartOn} –{" "}
                        {quote.estimatedWorkFinishOn}
                      </p>
                    ) : (
                      <p>No work dates supplied.</p>
                    )}
                    <p>
                      <strong>Received:</strong> {quote.receivedOn}
                    </p>
                    {quote.validThrough && (
                      <p>
                        <strong>Valid through:</strong> {quote.validThrough}
                      </p>
                    )}
                    {quote.termsNotes && <p>{quote.termsNotes}</p>}
                    <details>
                      <summary>Documents and history ({quote.documentCount})</summary>
                      {quote.replacesQuoteId && (
                        <p>Replaces an earlier quote; the original remains in this comparison.</p>
                      )}
                      {quote.withdrawnAt && (
                        <p>
                          Withdrawn {formatHomeTime(quote.withdrawnAt)}
                          {quote.withdrawalReason ? ` · ${quote.withdrawalReason}` : ""}
                        </p>
                      )}
                      {documents(quote.id)}
                      <Link
                        state={{ returnTo: `/maintenance?record=issue&id=${id}` }}
                        to={`${workflowUrl("file.upload")}&entityType=maintenance_quote&entityId=${quote.id}&purpose=supporting_document`}
                      >
                        Attach supporting document
                      </Link>
                    </details>
                  </td>
                  <td>
                    <span className="maintenance-record-status">
                      {quote.withdrawnAt ? "Withdrawn" : "Received"}
                    </span>
                    {quote.isCurrentAssignment && <p>Currently assigned</p>}
                    {quote.isHistoricalAssignment && <p>Previously assigned</p>}
                    {active &&
                      (quote.withdrawnAt ? (
                        <p>
                          <Link
                            to={`${workflowUrl("maintenance.quote.create", id)}&replacesQuoteId=${quote.id}`}
                          >
                            Replace withdrawn quote
                          </Link>
                        </p>
                      ) : (
                        <>
                          <p>
                            <Link
                              to={`${workflowUrl("maintenance.assignment.create", id)}&quoteId=${quote.id}&providerPartyId=${quote.providerPartyId}`}
                            >
                              Review assignment for {quote.label}
                            </Link>
                          </p>
                          <CommandLinks
                            target={id}
                            child={quote.id}
                            keys={["maintenance.quote.withdraw"]}
                            title={`Actions for ${quote.label}`}
                            asButtons
                            collapsible={false}
                          />
                        </>
                      ))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
