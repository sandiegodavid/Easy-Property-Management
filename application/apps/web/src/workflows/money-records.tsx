import { useQuery } from "@tanstack/react-query";
import { ParentBackLink, SourceWorkflowLink as Link } from "../shared/home-navigation";
import { api } from "@epm/contracts";
import { record, scalar } from "@epm/contracts/workflows";
import { useWorkspace } from "../app/workspace-gate";
import { CommandLinks, workflowUrl } from "./command";
import { label } from "./fields";
import { History, readResult } from "./reads";
export { MoneyFacts } from "./money-presentation";
import { MoneyFacts } from "./money-presentation";
import { CheckContext } from "./check-context";
import { RentExpectationDetail } from "./rent-expectation-detail";
import { RentReceiptDetail } from "./rent-receipt-detail";
import { ExpenseDetail, ExpenseCategoryDetail } from "./expense-detail";
import { EvidenceItem } from "./evidence-item";

export type MoneyKind =
  | "expectation"
  | "receipt"
  | "expense"
  | "check"
  | "report"
  | "deposit"
  | "settlement"
  | "category";
export function moneyRecordUrl(kind: MoneyKind, id: string) {
  return `/money?record=${kind}&id=${encodeURIComponent(id)}`;
}

export async function loadMoneyRecord(
  kind: MoneyKind,
  id: string,
  signal?: AbortSignal,
): Promise<Record<string, unknown>> {
  switch (kind) {
    case "expectation":
      return record(
        readResult(
          await api.GET("/api/rent-expectations/{expectation_id}", {
            signal,
            params: { path: { expectation_id: id } },
          }),
        ),
      );
    case "receipt":
      return record(
        readResult(
          await api.GET("/api/rent-receipts/{receipt_id}", {
            signal,
            params: { path: { receipt_id: id } },
          }),
        ),
      );
    case "expense":
      return record(
        readResult(
          await api.GET("/api/expenses/{expense_id}", {
            signal,
            params: { path: { expense_id: id } },
          }),
        ),
      );
    case "check":
      return record(
        readResult(
          await api.GET("/api/prepaid-checks/{check_id}", {
            signal,
            params: { path: { check_id: id } },
          }),
        ),
      );
    case "report":
      return record(
        readResult(
          await api.GET("/api/owner-rent-reports/{report_id}", {
            signal,
            params: { path: { report_id: id } },
          }),
        ),
      );
    case "deposit":
      return record(
        readResult(
          await api.GET("/api/security-deposits/{account_id}", {
            signal,
            params: { path: { account_id: id } },
          }),
        ),
      );
    case "settlement":
      return record(
        readResult(
          await api.GET("/api/security-deposit-settlements/{settlement_id}", {
            signal,
            params: { path: { settlement_id: id } },
          }),
        ),
      );
    case "category": {
      const items = readResult(
        await api.GET("/api/expense-categories", {
          signal,
          params: { query: { includeArchived: true } },
        }),
      );
      const item = items.find((item) => item.id === id);
      if (!item) throw new Error("Expense category unavailable.");
      return record(item);
    }
  }
}

const detailFields = [
  "status",
  "lifecycleStatus",
  "leaseId",
  "propertyId",
  "spaceId",
  "payeeName",
  "ownerDisplayNameSnapshot",
  "currentOwnerState",
  "reportedAtUtc",
  "propertyTimezoneSnapshot",
  "receiptLifecycleStatus",
  "financiallyEffective",
  "reportRevision",
  "displayName",
  "description",
  "notes",
  "sourceNote",
  "reviewNote",
  "dueOn",
  "periodStartsOn",
  "periodEndsOn",
  "receivedOn",
  "paidOn",
  "checkDatedOn",
  "paymentMethodKind",
  "paymentMethodLabel",
  "maskedReference",
  "otherPaymentMethodNote",
  "receivedByPartyId",
  "amountMinor",
  "expectedAmountMinor",
  "receivedAmountMinor",
  "outstandingAmountMinor",
  "amount",
  "activeRefundedAmount",
  "netAmount",
  "agreedAmount",
  "activeReceivedAmount",
  "varianceAmount",
  "settlementStatus",
  "timelinessStatus",
  "scheduleAnchorOn",
  "isProrated",
  "prorationNumeratorDays",
  "prorationDenominatorDays",
  "responsibilityBoundaryOn",
  "responsibilityOverrideReason",
  "receiptLifecycleStatus",
  "financiallyEffective",
  "depositEligibility",
  "reminderStatus",
  "voidReason",
  "voidedAt",
  "priorReportId",
  "replacementReportId",
  "replacementReceiptId",
  "replacesReceiptId",
  "replacesExpenseId",
  "replacesPrepaidCheckId",
  "replacedByPrepaidCheckId",
  "settlementDueOn",
  "legalRuleReference",
  "reviewNotes",
  "deadlineState",
  "unresolvedBalance",
  "replacesSettlementId",
  "replacedBySettlementId",
  "refundDue",
  "receiptTotal",
  "deductionTotal",
  "creditTotal",
  "unsettledReceiptAmount",
  "inspectionWarnings",
  "sourceWarnings",
  "createdAt",
  "updatedAt",
];
export function MoneyRecord({ kind, id }: { kind: MoneyKind; id: string }) {
  const { scope } = useWorkspace();
  const query = useQuery({
    queryKey: scope.key("money-record", kind, id),
    queryFn: ({ signal }) => loadMoneyRecord(kind, id, signal),
  });
  if (query.isPending || query.error)
    return (
      <>
        <ParentBackLink to="/money">← Back to Money</ParentBackLink>
        {query.error ? (
          <p role="alert">{query.error.message}</p>
        ) : (
          <p role="status">Loading money record…</p>
        )}
      </>
    );
  const item = query.data,
    leaseId = scalar(item.leaseId),
    accountId = kind === "deposit" ? id : scalar(item.accountId);
  const rentActions =
    kind === "expectation"
      ? [
          "finance.rent_receipt.create",
          "finance.prepaid_check.create",
          "finance.rent_expectation.void",
          "finance.rent_expectation.timeliness_review",
        ]
      : kind === "receipt"
        ? ["finance.rent_receipt.void"]
        : kind === "check"
          ? item.status === "scheduled"
            ? [
                ...(item.depositEligibility === "eligible"
                  ? ["finance.prepaid_check.deposit"]
                  : []),
                "finance.prepaid_check.void",
              ]
            : item.status === "deposited"
              ? ["finance.prepaid_check.return"]
              : (item.status === "returned" || item.status === "voided") &&
                  !item.replacedByPrepaidCheckId
                ? ["finance.prepaid_check.replace"]
                : []
          : [];
  return (
    <section
      aria-label="Money record"
      className={
        ["expectation", "receipt", "expense", "category"].includes(kind) ? "rent-detail" : undefined
      }
    >
      <ParentBackLink to={kind === "category" ? "/money?tab=categories" : "/money"}>
        ← Back to {kind === "category" ? "Expense categories" : "Money"}
      </ParentBackLink>
      <h2>
        {kind === "expectation"
          ? "Rent due"
          : kind === "category"
            ? scalar(item.displayName, "Expense category")
            : kind === "expense"
              ? "Paid expense"
              : kind === "receipt"
                ? "Rent payment"
                : `${label(kind)} record`}
      </h2>
      {kind === "expectation" ? (
        <RentExpectationDetail item={item} />
      ) : kind === "receipt" ? (
        <RentReceiptDetail item={item} />
      ) : kind === "expense" ? (
        <ExpenseDetail item={item} />
      ) : kind === "category" ? (
        <ExpenseCategoryDetail item={item} />
      ) : (
        <MoneyFacts value={item} fields={detailFields} />
      )}
      {kind === "check" && <CheckContext check={item} />}
      {(leaseId || !!item.propertyId) && (
        <nav aria-label="Related money records">
          {leaseId && <Link to={`/leases/${leaseId}/details`}>View lease</Link>}
          {!!item.propertyId && (
            <Link to={`/properties/${scalar(item.propertyId)}/money`}>View property money</Link>
          )}
        </nav>
      )}
      {rentActions.length > 0 && !item.voidedAt && (
        <CommandLinks
          keys={rentActions}
          target={leaseId}
          child={id}
          title="Rent ledger actions"
          collapsible={kind !== "expectation" && kind !== "receipt"}
          asButtons={kind === "expectation" || kind === "receipt"}
          labels={{
            "finance.rent_receipt.create": "Record payment",
            "finance.prepaid_check.create": "Record prepaid check",
            "finance.rent_expectation.void": "Void rent expectation",
            "finance.rent_expectation.timeliness_review": "Review payment timing",
            "finance.rent_receipt.void": "Void payment",
          }}
        />
      )}
      {kind === "expense" && !item.voidedAt && (
        <CommandLinks
          keys={["finance.expense.patch", "finance.expense.void", "finance.expense_refund.create"]}
          target={id}
          asButtons
          collapsible={false}
          labels={{
            "finance.expense.patch": "Edit expense notes",
            "finance.expense.void": "Void expense",
            "finance.expense_refund.create": "Record refund",
          }}
        />
      )}
      {kind === "expense" && !!item.voidedAt && (
        <Link
          to={`${workflowUrl("finance.expense.create")}&replacesExpenseId=${id}&propertyId=${scalar(item.propertyId)}`}
        >
          Record replacement expense
        </Link>
      )}
      {kind === "receipt" && !!item.voidedAt && (
        <Link to={`${workflowUrl("finance.rent_receipt.create", leaseId)}&replacesReceiptId=${id}`}>
          Record replacement rent receipt
        </Link>
      )}
      {kind === "category" && (
        <CommandLinks
          asButtons
          collapsible={false}
          keys={
            item.archivedAt
              ? ["finance.expense_category.restore"]
              : ["finance.expense_category.patch", "finance.expense_category.archive"]
          }
          target={id}
        />
      )}
      {kind === "report" && item.status === "pending" && (
        <CommandLinks
          keys={["owner_rent_report.patch", "owner_rent_report.verify", "owner_rent_report.reject"]}
          target={id}
        />
      )}
      {kind === "report" && item.status !== "pending" && (
        <Link
          to={`${workflowUrl("owner_rent_report.create")}&replacesReportId=${id}&leaseId=${leaseId}`}
        >
          Record correction report
        </Link>
      )}
      {kind === "report" && !!item.verifiedReceiptId && (
        <Link to={moneyRecordUrl("receipt", scalar(item.verifiedReceiptId))}>
          Verified Finance receipt
        </Link>
      )}
      {kind === "report" && (
        <>
          <p>
            A retained Owner claim is not income. Only the active Finance receipt counts; voiding it
            leaves this verification history financially ineffective.
          </p>
          {(["priorReportId", "replacementReportId"] as const).map(
            (key) =>
              item[key] && (
                <p key={key}>
                  {key === "priorReportId" ? "Prior report" : "Replacement report"}:{" "}
                  <Link to={moneyRecordUrl("report", scalar(item[key]))}>
                    Review report history
                  </Link>
                </p>
              ),
          )}
          {item.replacementReceiptId && (
            <Link to={moneyRecordUrl("receipt", scalar(item.replacementReceiptId))}>
              Replacement Finance receipt
            </Link>
          )}
        </>
      )}
      {kind === "deposit" && (
        <>
          <CommandLinks
            keys={["finance.deposit_receipt.create", "finance.deposit_settlement.create"]}
            target={id}
          />
          <DepositHistory id={id} />
          {item.settlementId && (
            <Link to={moneyRecordUrl("settlement", scalar(item.settlementId))}>
              Current settlement
            </Link>
          )}
        </>
      )}
      {kind === "settlement" && (
        <>
          <Link to={moneyRecordUrl("deposit", accountId)}>Deposit account</Link>
          <CommandLinks
            target={accountId}
            child={id}
            keys={
              item.status === "draft"
                ? [
                    "finance.deposit_settlement.patch",
                    "finance.deposit_deduction.create",
                    "finance.deposit_credit.create",
                    "finance.deposit_settlement.approve",
                    "finance.deposit_settlement.void",
                  ]
                : item.status === "approved"
                  ? [
                      "finance.deposit_refund.create",
                      "finance.deposit_settlement.complete",
                      "finance.deposit_settlement.void",
                    ]
                  : item.status === "completed"
                    ? ["finance.deposit_settlement.void"]
                    : []
            }
          />
          {item.status === "voided" && (
            <Link
              to={`${workflowUrl("finance.deposit_settlement.create", accountId)}&replacesSettlementId=${id}`}
            >
              Prepare replacement settlement
            </Link>
          )}
        </>
      )}
      {[
        "allocations",
        "allocationSummaries",
        "receiptAllocations",
        "timelinessReviews",
        "refunds",
        "deductions",
        "credits",
        "correctionChain",
      ].map(
        (name) =>
          !(kind === "receipt" && name === "allocations") &&
          Array.isArray(item[name]) && (
            <section key={name} aria-label={label(name)}>
              <h3>{label(name)}</h3>
              {(item[name] as unknown[]).map((entry) => {
                const child = record(entry),
                  childId = scalar(child.id ?? child.receiptId ?? child.allocationId);
                return (
                  <article key={childId}>
                    <MoneyFacts
                      value={child}
                      fields={[
                        ...detailFields,
                        "rationale",
                        "kind",
                        "category",
                        "expectationId",
                        "receiptId",
                        "recipientName",
                        "receivedFromName",
                        "authorizedBySettlementId",
                        "reason",
                        "decision",
                        "calculatorPrincipal",
                        "annualRateBasisPoints",
                        "startsOn",
                        "endsOn",
                        "dayCount",
                        "calculatedAmount",
                        "overrideReason",
                      ]}
                    />
                    {!!child.expectationId && (
                      <Link to={moneyRecordUrl("expectation", scalar(child.expectationId))}>
                        Allocated expectation
                      </Link>
                    )}
                    {!!child.receiptId && (
                      <Link to={moneyRecordUrl("receipt", scalar(child.receiptId))}>
                        Recorded receipt for this allocation
                      </Link>
                    )}
                    {kind === "expense" &&
                      name === "refunds" &&
                      !item.voidedAt &&
                      !child.voidedAt && (
                        <CommandLinks
                          keys={["finance.expense_refund.void"]}
                          target={id}
                          child={childId}
                        />
                      )}
                    {kind === "expense" &&
                      name === "refunds" &&
                      !!child.voidedAt &&
                      !item.voidedAt && (
                        <Link
                          to={`${workflowUrl("finance.expense_refund.create", id)}&replacesRefundId=${childId}`}
                        >
                          Record replacement refund
                        </Link>
                      )}
                    {kind === "settlement" &&
                      item.status === "draft" &&
                      (name === "deductions" || name === "credits") && (
                        <CommandLinks
                          keys={
                            name === "deductions"
                              ? [
                                  "finance.deposit_deduction.update",
                                  "finance.deposit_deduction.delete",
                                  "finance.deposit_deduction_source.add",
                                ]
                              : ["finance.deposit_credit.update", "finance.deposit_credit.delete"]
                          }
                          target={accountId}
                          child={childId}
                        />
                      )}
                    {kind === "settlement" && name === "refunds" && !child.voidedAt && (
                      <CommandLinks
                        keys={["finance.deposit_refund.void"]}
                        target={accountId}
                        child={childId}
                      />
                    )}
                    {kind === "settlement" &&
                      name === "refunds" &&
                      !!child.voidedAt &&
                      item.status === "approved" && (
                        <Link
                          to={`${workflowUrl("finance.deposit_refund.create", accountId, id)}&replacesRefundId=${childId}`}
                        >
                          Record replacement deposit refund
                        </Link>
                      )}
                    {name === "deductions" && (
                      <>
                        <MoneyEvidence
                          value={child.evidence}
                          archiveContext={
                            item.status === "draft" ? { accountId, settlementId: id } : undefined
                          }
                        />
                        {Array.isArray(child.evidence) &&
                          child.evidence.some((entry) => !!record(entry).archivedAt) && (
                            <details>
                              <summary>Archived deduction evidence history</summary>
                              <MoneyEvidence value={child.evidence} history />
                            </details>
                          )}
                        {item.status === "draft" && (
                          <Link
                            to={`${workflowUrl("file.upload")}&entityType=security_deposit_deduction&entityId=${childId}&accountId=${accountId}`}
                          >
                            Attach deduction evidence
                          </Link>
                        )}
                        {Array.isArray(child.sources) &&
                          child.sources.map((source) => {
                            const fact = record(source);
                            return (
                              <article key={scalar(fact.id)}>
                                <MoneyFacts
                                  value={fact}
                                  fields={[
                                    "sourceKind",
                                    "sourceSummary",
                                    "outstandingAmount",
                                    "historicalConfirmed",
                                    "historicalReason",
                                  ]}
                                />
                                {item.status === "draft" && (
                                  <CommandLinks
                                    keys={["finance.deposit_deduction_source.delete"]}
                                    target={accountId}
                                    child={scalar(fact.id)}
                                  />
                                )}
                              </article>
                            );
                          })}
                      </>
                    )}
                  </article>
                );
              })}
            </section>
          ),
      )}
      <MoneyEvidence
        value={item.activeEvidence ?? item.files ?? item.evidence}
        allowArchive={kind === "expense" || kind === "report"}
        archiveContext={
          kind === "settlement" && item.status === "draft"
            ? { accountId, settlementId: id }
            : undefined
        }
      />
      {(Array.isArray(item.archivedEvidence) || Array.isArray(item.files)) && (
        <details>
          <summary>Archived evidence history</summary>
          <MoneyEvidence value={item.archivedEvidence ?? item.files} history />
        </details>
      )}
      {(kind === "expense" || kind === "report") && (
        <Link
          to={`${workflowUrl("file.upload")}&entityType=${kind === "expense" ? "expense" : "owner_rent_report"}&entityId=${id}`}
        >
          Attach supporting evidence to this record
        </Link>
      )}
      <History
        kind={
          {
            expectation: "rent_expectation",
            receipt: "rent_receipt",
            expense: "expense",
            check: "prepaid_check",
            report: "owner_rent_report",
            deposit: "security_deposit_account",
            settlement: "security_deposit_settlement",
            category: "expense_category",
          }[kind]
        }
        id={id}
      />
    </section>
  );
}
function MoneyEvidence({
  value,
  history = false,
  allowArchive = false,
  archiveContext,
}: {
  value: unknown;
  history?: boolean;
  allowArchive?: boolean;
  archiveContext?: { accountId: string; settlementId: string };
}) {
  if (!Array.isArray(value)) return null;
  return (
    <section aria-label="Supporting evidence">
      <h3>Supporting evidence</h3>
      {value
        .filter((entry) => !!(record(entry).archivedAt ?? record(entry).archived_at) === history)
        .map((value) => {
          const item = record(value),
            fileId = scalar(item.fileId ?? item.file_id ?? item.id);
          const available =
            (item.available === true ||
              item.storageState === "available" ||
              item.storage_state === "available") &&
            !item.archivedAt &&
            !item.archived_at;
          return (
            <EvidenceItem
              key={scalar(item.linkId ?? item.id ?? fileId)}
              name={scalar(item.originalName ?? item.original_name, "Supporting evidence")}
              state={history ? "Archived association" : available ? "Available" : "Unavailable"}
            >
              {history && (
                <p className="evidence-item-note">
                  Archived association:{" "}
                  {scalar(item.archiveReason ?? item.archive_reason, "Retained history")}
                </p>
              )}
              {!history && !available && (
                <p className="evidence-item-note">
                  Content availability must be verified before opening.
                </p>
              )}
              {available && <a href={`/api/files/${fileId}/content`}>Download evidence</a>}{" "}
              <Link to={`/money?file=${fileId}`}>Evidence metadata and history</Link>
              {allowArchive && !history && (
                <Link
                  to={`/money?workflow=file.link.archive&target=${scalar(item.linkId ?? item.id)}${item.entity_type === "owner_rent_report" ? "&reportEvidence=true" : ""}`}
                >
                  Archive evidence association
                </Link>
              )}
              {archiveContext && !history && (
                <Link
                  to={`/money?workflow=file.link.archive&target=${scalar(item.linkId)}&accountId=${archiveContext.accountId}&settlementId=${archiveContext.settlementId}`}
                >
                  Archive deposit evidence association
                </Link>
              )}
            </EvidenceItem>
          );
        })}
    </section>
  );
}
function DepositHistory({ id }: { id: string }) {
  const { scope } = useWorkspace();
  const receipts = useQuery({
    queryKey: scope.key("deposit-receipt-history", id),
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/security-deposits/{account_id}/receipts", {
          signal,
          params: { path: { account_id: id } },
        }),
      ),
  });
  const refunds = useQuery({
    queryKey: scope.key("deposit-refund-history", id),
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/security-deposits/{account_id}/refunds", {
          signal,
          params: { path: { account_id: id } },
        }),
      ),
  });
  return (
    <>
      {receipts.error && (
        <p role="alert">Deposit receipt history unavailable: {receipts.error.message}</p>
      )}
      {refunds.error && (
        <p role="alert">Deposit refund history unavailable: {refunds.error.message}</p>
      )}
      {receipts.isPending && <p role="status">Loading deposit receipts…</p>}
      {receipts.data?.map((receipt) => (
        <article key={receipt.id}>
          <MoneyFacts
            value={receipt}
            fields={[
              "receivedOn",
              "amount",
              "receivedFromName",
              "receivedByName",
              "lifecycleStatus",
              "voidReason",
              "replacesReceiptId",
              "replacedByReceiptId",
            ]}
          />
          {receipt.lifecycleStatus === "active" && (
            <CommandLinks keys={["finance.deposit_receipt.void"]} target={id} child={receipt.id} />
          )}
          {receipt.lifecycleStatus === "voided" && !receipt.replacedByReceiptId && (
            <Link
              to={`${workflowUrl("finance.deposit_receipt.create", id)}&replacesReceiptId=${receipt.id}`}
            >
              Record replacement deposit receipt
            </Link>
          )}
        </article>
      ))}
      {refunds.data?.map((refund) => (
        <MoneyFacts
          key={refund.id}
          value={refund}
          fields={[
            "paidOn",
            "amount",
            "recipientName",
            "lifecycleStatus",
            "voidReason",
            "replacesRefundId",
            "replacedByRefundId",
          ]}
        />
      ))}
    </>
  );
}
