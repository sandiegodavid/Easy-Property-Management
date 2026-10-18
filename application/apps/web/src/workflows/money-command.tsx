import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { ParentBackLink } from "../shared/home-navigation";
import { api } from "@epm/contracts";
import type { components } from "@epm/contracts/generated";
import { workflows, record, scalar, type Workflow } from "@epm/contracts/workflows";
import { useWorkspace } from "../app/workspace-gate";
import { CommandLoader } from "./command";
import { readResult } from "./reads";
import { loadMoneyRecord, MoneyFacts, moneyRecordUrl, type MoneyKind } from "./money-records";
import { ExpenseContext } from "./expense-context";
import { CheckContext } from "./check-context";
import { OwnerReportContext, ownerVerificationProblem } from "./owner-report-context";
import { type Choices } from "./fields";
import {
  DepositContext,
  InterestCreditReview,
  DeductionSourceReview,
  creditReady,
  depositDuplicates,
  sourceReviewKey,
} from "./deposit-context";
import {
  RentScheduleContext,
  ReceiptAllocationContext,
  PaymentMethodReview,
  paymentMethodProblem,
  receiptBalance,
  scheduleKey,
} from "./rent-context";

type Source = {
  revision: number;
  value: Record<string, unknown>;
  children: Record<string, unknown>[];
  choices: Choices;
  ledgerRevision?: number;
  receiptSuggestion?: Record<string, unknown>;
};
async function commandSource(
  definition: Workflow,
  target: string | undefined,
  child: string | undefined,
  leaseId: string | undefined,
  signal?: AbortSignal,
): Promise<Source> {
  const source: Source = { revision: 0, value: {}, children: [], choices: {} };
  if (definition.sourceKind === "lease" && target) {
    const [ledger, lease, expectations] = await Promise.all([
      api
        .GET("/api/leases/{lease_id}/rent-ledger", {
          signal,
          params: { path: { lease_id: target } },
        })
        .then(readResult),
      api
        .GET("/api/leases/{lease_id}", { signal, params: { path: { lease_id: target } } })
        .then(readResult),
      api
        .GET("/api/rent-expectations", {
          signal,
          params: { query: { leaseId: target, pageSize: 100 } },
        })
        .then(readResult),
    ]);
    source.revision = ledger.rentLedgerRevision;
    source.value = record(lease);
    if (definition.formKey.startsWith("finance.prepaid_check.")) {
      const space = readResult(
        await api.GET("/api/spaces/{space_id}/status", {
          signal,
          params: { path: { space_id: lease.spaceId } },
        }),
      );
      source.value.propertyId = space.propertyId;
    }
    source.choices.leaseTermId = lease.terms.map((term) => ({
      id: term.id,
      label: `${term.effectiveOn} · ${term.paymentFrequency}`,
    }));
    source.choices.expectationId = expectations.items
      .filter(
        (item) =>
          item.outstandingAmountMinor > 0 &&
          (!definition.formKey.startsWith("finance.prepaid_check.") ||
            (!item.isProrated && item.outstandingAmountMinor === item.expectedAmountMinor)),
      )
      .map((item) => ({
        id: item.id,
        label: `${item.periodStartsOn} – ${item.periodEndsOn} · ${item.outstandingAmountMinor} cents outstanding`,
      }));
    source.choices.payerPartyId = lease.participants.map((item) => ({
      id: item.tenantPartyId,
      label: `${item.tenantPartyId} · ${item.startsOn} – ${item.endsOn ?? "ongoing"}`,
    }));
    if (definition.formKey === "finance.rent_receipt.create") {
      const suggestion = await api.GET(
        "/api/leases/{lease_id}/rent-receipts/payment-method-suggestion",
        {
          signal,
          params: { path: { lease_id: target } },
        },
      );
      source.receiptSuggestion =
        suggestion.response.status === 204 ? {} : record(readResult(suggestion));
    }
    if (child) {
      const kind =
        definition.childKey === "expectationId" ||
        definition.formKey === "finance.prepaid_check.create" ||
        definition.formKey === "finance.rent_receipt.create"
          ? "expectation"
          : definition.childKey === "receiptId"
            ? "receipt"
            : "check";
      const value = await loadMoneyRecord(kind, child, signal);
      if (value.leaseId !== target)
        throw new Error("This record does not belong to the selected rent ledger.");
      source.children = [value];
      if (definition.formKey === "finance.prepaid_check.deposit") {
        const receipts = readResult(
          await api.GET("/api/rent-receipts", {
            signal,
            params: { query: { leaseId: target, pageSize: 100 } },
          }),
        );
        source.choices.existingReceiptId = receipts.items
          .filter(
            (receipt) =>
              !receipt.voidedAt &&
              receipt.paymentMethodKind === "check" &&
              receipt.amountMinor === value.amountMinor &&
              receipt.allocations.length === 1 &&
              receipt.allocations[0].expectationId === value.expectationId &&
              receipt.allocations[0].amountMinor === value.amountMinor,
          )
          .map((receipt) => ({
            id: receipt.id,
            label: `${receipt.receivedOn} · ${receipt.amountMinor} cents · check`,
          }));
      }
    }
  } else if (target && definition.sourceKind) {
    const kind: MoneyKind =
      definition.sourceKind === "expense"
        ? "expense"
        : definition.sourceKind === "expense_category"
          ? "category"
          : definition.sourceKind === "owner_rent_report"
            ? "report"
            : "deposit";
    source.value = await loadMoneyRecord(kind, target, signal);
    source.revision = Number(
      source.value.expenseRevision ??
        source.value.depositAccountRevision ??
        source.value.reportRevision ??
        source.value.revision,
    );
    if (kind === "expense")
      source.children = Array.isArray(source.value.refunds) ? source.value.refunds.map(record) : [];
    if (kind === "deposit") {
      const receipts = readResult(
        await api.GET("/api/security-deposits/{account_id}/receipts", {
          signal,
          params: { path: { account_id: target } },
        }),
      );
      const refunds = readResult(
        await api.GET("/api/security-deposits/{account_id}/refunds", {
          signal,
          params: { path: { account_id: target } },
        }),
      );
      source.children = [...receipts.map(record), ...refunds.map(record)];
      if (source.value.settlementId) {
        const settlement = await loadMoneyRecord(
          "settlement",
          scalar(source.value.settlementId),
          signal,
        );
        source.children.push(settlement);
        for (const key of ["deductions", "credits"])
          if (Array.isArray(settlement[key]))
            for (const item of settlement[key] as unknown[]) {
              source.children.push(record(item));
              if (Array.isArray(record(item).sources))
                source.children.push(...(record(item).sources as unknown[]).map(record));
            }
      }
    }
    if (kind === "report" && definition.formKey.endsWith(".verify")) {
      if (source.value.replacesReportId) {
        const prior = await loadMoneyRecord(
          "report",
          scalar(source.value.replacesReportId),
          signal,
        );
        source.value.priorVerifiedReceiptId = prior.verifiedReceiptId;
        source.value.priorReceiptLifecycleStatus = prior.receiptLifecycleStatus;
        if (prior.verifiedReceiptId)
          source.receiptSuggestion = { replacesReceiptId: prior.verifiedReceiptId };
      }
      const id = scalar(source.value.leaseId);
      source.ledgerRevision = readResult(
        await api.GET("/api/leases/{lease_id}/rent-ledger", {
          signal,
          params: { path: { lease_id: id } },
        }),
      ).rentLedgerRevision;
      const expectations = readResult(
        await api.GET("/api/rent-expectations", {
          signal,
          params: { query: { leaseId: id, pageSize: 100 } },
        }),
      );
      const receipts = readResult(
        await api.GET("/api/rent-receipts", {
          signal,
          params: { query: { leaseId: id, pageSize: 100 } },
        }),
      );
      source.choices.expectationId = expectations.items.map((item) => ({
        id: item.id,
        label: `${item.periodStartsOn} · ${item.outstandingAmountMinor} cents outstanding`,
      }));
      source.choices.existingReceiptId = receipts.items
        .filter(
          (item) =>
            !item.voidedAt &&
            (!source.value.priorVerifiedReceiptId ||
              item.replacesReceiptId === source.value.priorVerifiedReceiptId) &&
            item.receivedOn === source.value.receivedOn &&
            item.amountMinor === source.value.amountMinor &&
            item.receivedByPartyId === source.value.ownerPartyId &&
            item.paymentMethodKind === source.value.paymentMethodKind &&
            item.paymentMethodLabel === source.value.paymentMethodLabel &&
            item.maskedReference === source.value.maskedReference &&
            item.otherPaymentMethodNote === source.value.otherPaymentMethodNote,
        )
        .map((item) => ({
          id: item.id,
          label: `${item.receivedOn} · ${item.amountMinor} cents · ${item.paymentMethodKind}`,
        }));
    }
  }
  if (leaseId && !definition.sourceKind) {
    const lease = readResult(
      await api.GET("/api/leases/{lease_id}", { signal, params: { path: { lease_id: leaseId } } }),
    );
    source.choices.leaseTermId = lease.terms.map((term) => ({
      id: term.id,
      label: `${term.effectiveOn} · ${term.paymentFrequency}`,
    }));
  }
  if (definition.formKey.startsWith("finance.expense.") && !definition.formKey.endsWith(".void")) {
    const categories = readResult(
      await api.GET("/api/expense-categories", {
        signal,
        params: { query: { includeArchived: true } },
      }),
    );
    source.choices.categoryId = categories.map((item) => ({
      id: item.id,
      label: `${item.displayName}${item.archivedAt ? " · Archived — historical confirmation required" : ""}`,
      historical: !!item.archivedAt,
    }));
  }
  return source;
}

export function MoneyCommand() {
  const [params] = useSearchParams();
  const definition = workflows.find((item) => item.formKey === params.get("workflow"));
  const target = params.get("target") ?? undefined,
    child = params.get("child") ?? undefined;
  const { scope } = useWorkspace();
  const [session] = useState(() => crypto.randomUUID());
  const [mode, setMode] = useState<"existing" | "create">();
  const [receiptKey] = useState(() => crypto.randomUUID());
  const [confirmedSchedule, setConfirmedSchedule] = useState<string>();
  const [confirmedInterest, setConfirmedInterest] = useState<string>();
  const [confirmedSource, setConfirmedSource] = useState<string>();
  const [expenseCandidates, setExpenseCandidates] = useState<
    components["schemas"]["ExpenseDuplicateCandidate"][]
  >([]);
  const replacement = params.get("replacesReceiptId");
  const expenseReplacement = params.get("replacesExpenseId");
  const reportReplacement = params.get("replacesReportId");
  const priorReport = useQuery({
    queryKey: scope.key("owner-report-replacement-command-source", session, reportReplacement),
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    enabled: definition?.formKey === "owner_rent_report.create" && !!reportReplacement,
    queryFn: async ({ signal }) => {
      const report = await loadMoneyRecord("report", reportReplacement!, signal);
      if (report.status === "pending" || report.replacementReportId)
        throw new Error("Select a terminal report without a replacement.");
      return report;
    },
  });
  const priorExpense = useQuery({
    queryKey: scope.key("expense-replacement-source", session, expenseReplacement),
    enabled: definition?.formKey === "finance.expense.create" && !!expenseReplacement,
    queryFn: async ({ signal }) => {
      const expense = await loadMoneyRecord("expense", expenseReplacement!, signal);
      if (!expense.voidedAt) throw new Error("Select a voided expense for replacement.");
      return expense;
    },
  });
  const priorReceipt = useQuery({
    queryKey: scope.key("rent-replacement-source", session, replacement),
    enabled: definition?.formKey === "finance.rent_receipt.create" && !!replacement,
    queryFn: async ({ signal }) => {
      const receipt = await loadMoneyRecord("receipt", replacement!, signal);
      if (receipt.leaseId !== target || !receipt.voidedAt)
        throw new Error("Select a voided receipt from this Lease for replacement.");
      return receipt;
    },
  });
  const resume = params.get("resume");
  const saved = useQuery({
    queryKey: scope.key("workflow-recovery", resume),
    enabled: !!resume,
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/operator/recovery/{record_id}", {
          signal,
          params: { path: { record_id: resume! } },
        }),
      ),
  });
  const selectedChild =
    child ??
    (definition?.childKey && saved.data
      ? scalar(saved.data.payload[definition.childKey])
      : undefined);
  const leaseId = (params.get("leaseId") ?? scalar(saved.data?.payload.leaseId)) || undefined;
  const source = useQuery({
    queryKey: scope.key("money-command-source", session, target, selectedChild, leaseId),
    enabled: !!definition && (!resume || !!saved.data),
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    queryFn: ({ signal }) => commandSource(definition!, target, selectedChild, leaseId, signal),
  });
  if (
    !definition ||
    !(
      definition.formKey.startsWith("finance.") ||
      definition.formKey.startsWith("owner_rent_report.") ||
      definition.formKey === "file.upload"
    )
  )
    return <p role="alert">Unsupported Money command.</p>;
  if (definition.sourceKind && !target)
    return <p role="alert">Select the owning money record first.</p>;
  if (
    source.isPending ||
    (priorReport.isEnabled && priorReport.isPending) ||
    (resume && saved.isPending) ||
    (definition.formKey === "finance.rent_receipt.create" &&
      replacement &&
      priorReceipt.isPending) ||
    (definition.formKey === "finance.expense.create" &&
      expenseReplacement &&
      priorExpense.isPending)
  )
    return <p role="status">Loading displayed money source…</p>;
  if (source.error || saved.error || priorReceipt.error || priorExpense.error)
    return (
      <p role="alert">
        {source.error?.message ??
          saved.error?.message ??
          priorReceipt.error?.message ??
          priorExpense.error?.message ??
          priorReport.error?.message}
      </p>
    );
  const state = source.data,
    selected = state.children.find((item) => item.id === selectedChild);
  const recoverMissing =
    saved.data?.formKey === definition.formKey &&
    saved.data.sourceId === target &&
    definition.childKey &&
    saved.data.payload[definition.childKey] === selectedChild &&
    (saved.data.status === "outcome_unknown" || !!saved.data.receipt);
  if (definition.childKey && !selected && !recoverMissing)
    return <p role="alert">This child does not belong to the selected money aggregate.</p>;
  const initial: Record<string, unknown> = {};
  if (priorReport.error) return <p role="alert">{priorReport.error.message}</p>;
  if (priorReport.data)
    for (const key of [
      "leaseId",
      "ownerPartyId",
      "receivedOn",
      "paymentMethodKind",
      "paymentMethodLabel",
      "maskedReference",
      "otherPaymentMethodNote",
      "sourceNote",
    ])
      initial[key] = priorReport.data[key] ?? undefined;
  if (/patch|update/.test(definition.formKey))
    for (const key of Object.keys(definition.schema.properties ?? {})) {
      if (definition.formKey === "finance.expense.patch" && key !== "notes") continue;
      const value = record(selected ?? state.value)[key];
      if (value !== undefined && value !== null && !key.startsWith("expected"))
        initial[key] = value;
    }
  for (const key of [
    "leaseId",
    "propertyId",
    "replacesExpenseId",
    "replacesReceiptId",
    "replacesReportId",
    "replacesSettlementId",
  ])
    if (params.get(key)) initial[key] = params.get(key);
  if (definition.formKey === "finance.rent_receipt.create") {
    Object.assign(initial, state.receiptSuggestion);
    initial.leaseId = target;
    initial.currencyCode = "USD";
    if (priorReceipt.data) {
      for (const key of [
        "receivedOn",
        "amountMinor",
        "paymentMethodKind",
        "paymentMethodLabel",
        "maskedReference",
        "otherPaymentMethodNote",
        "receivedByPartyId",
        "notes",
        "allocations",
      ])
        initial[key] = priorReceipt.data[key];
    }
    if (selected && !priorReceipt.data) {
      initial.amountMinor = selected.outstandingAmountMinor;
      initial.allocations = [
        { expectationId: selected.id, amountMinor: selected.outstandingAmountMinor },
      ];
    }
  }
  if (definition.formKey === "finance.prepaid_check.create" && selected)
    initial.expectationId = selected.id;
  if (definition.formKey === "finance.prepaid_check.replace" && selected)
    for (const key of [
      "expectationId",
      "payerPartyId",
      "receivedOn",
      "checkDatedOn",
      "maskedReference",
    ])
      initial[key] = selected[key] ?? undefined;
  if (definition.formKey === "finance.expense.create")
    Object.assign(initial, { paidByKind: "local_operator", currencyCode: "USD" });
  if (priorExpense.data) {
    for (const key of [
      "propertyId",
      "spaceId",
      "categoryId",
      "providerPartyId",
      "paidByKind",
      "paidByPartyId",
      "paidOn",
      "amount",
      "description",
      "reference",
      "notes",
    ])
      initial[key] = priorExpense.data[key];
    initial.payeeName = priorExpense.data.providerPartyId ? undefined : priorExpense.data.payeeName;
  }
  if (definition.formKey === "finance.expense_refund.create" && params.has("replacesRefundId")) {
    const prior = state.children.find((item) => item.id === params.get("replacesRefundId"));
    if (!prior?.voidedAt)
      return <p role="alert">Select a voided refund from this Expense for replacement.</p>;
    for (const key of ["amount", "receivedOn", "notes"]) initial[key] = prior[key];
    initial.currencyCode = "USD";
    initial.replacesRefundId = prior.id;
  }
  if (definition.formKey === "finance.deposit_receipt.create")
    Object.assign(initial, { currencyCode: "USD", receivedByKind: "local_operator" });
  if (definition.formKey === "finance.deposit_refund.create") initial.currencyCode = "USD";
  if (definition.formKey === "finance.deposit_receipt.create" && params.has("replacesReceiptId")) {
    const prior = state.children.find((item) => item.id === params.get("replacesReceiptId"));
    if (!prior?.voidedAt)
      return <p role="alert">Select a voided receipt from this deposit account.</p>;
    for (const key of [
      "receivedOn",
      "amount",
      "receivedFromPartyId",
      "receivedByKind",
      "receivedByPartyId",
      "reference",
      "notes",
    ])
      initial[key] = prior[key];
  }
  if (definition.formKey === "finance.deposit_refund.create" && params.has("replacesRefundId")) {
    const prior = state.children.find((item) => item.id === params.get("replacesRefundId"));
    if (!prior?.voidedAt)
      return <p role="alert">Select a voided refund from this deposit account.</p>;
    for (const key of ["paidOn", "amount", "recipientPartyId", "reference", "notes"])
      initial[key] = prior[key];
    initial.replacesRefundId = prior.id;
  }
  if (definition.formKey === "file.upload")
    Object.assign(initial, {
      entityType: params.get("entityType"),
      entityId: params.get("entityId"),
      purpose: params.get("purpose") ?? "supporting_document",
    });
  if (state.ledgerRevision !== undefined) initial.expectedRentLedgerRevision = state.ledgerRevision;
  const verification = definition.formKey === "owner_rent_report.verify";
  const selectedMode =
    mode ??
    (saved.data
      ? saved.data.payload.existingReceiptId
        ? "existing"
        : "create"
      : params.get("receiptMode") === "existing"
        ? "existing"
        : undefined);
  if (verification && !saved.data) {
    if (selectedMode === "create") {
      Object.assign(initial, state.receiptSuggestion);
      initial.receiptIdempotencyKey = receiptKey;
      initial.allocations = [{}];
    }
  }
  const parentTarget =
    definition.formKey === "file.upload" && leaseId
      ? `/leases/${leaseId}/details`
      : definition.sourceKind === "lease"
        ? `/money?leaseId=${target}`
        : target
          ? moneyRecordUrl(
              definition.sourceKind === "expense"
                ? "expense"
                : definition.sourceKind === "owner_rent_report"
                  ? "report"
                  : definition.sourceKind === "security_deposit_account"
                    ? "deposit"
                    : "category",
              target,
            )
          : "/money";
  const editor = verification
    ? {
        ...definition,
        schema: {
          ...definition.schema,
          properties: Object.fromEntries(
            Object.entries(definition.schema.properties ?? {}).filter(([key]) =>
              selectedMode === "create"
                ? key !== "existingReceiptId"
                : !["receiptIdempotencyKey", "allocations", "replacesReceiptId"].includes(key),
            ),
          ),
        },
      }
    : definition;
  return (
    <>
      <ParentBackLink to={parentTarget} />
      <MoneyFacts
        value={selected ?? state.value}
        fields={[
          "id",
          "status",
          "amountMinor",
          "outstandingAmountMinor",
          "amount",
          "receivedOn",
          "refundDue",
          "settlementStatus",
          "voidedAt",
        ]}
      />
      <p>
        Amounts ending in Minor are integer USD cents. Decimal amounts require exactly two decimal
        places. Allocation amounts must total the receipt; review the displayed outstanding balance.
      </p>
      {state.ledgerRevision !== undefined && (
        <p>Displayed rent-ledger revision: {state.ledgerRevision}</p>
      )}
      {verification && (
        <fieldset disabled={!!selectedMode}>
          <legend>Receipt verification choice</legend>
          <label>
            <input
              type="radio"
              name="verificationMode"
              checked={selectedMode === "existing"}
              onChange={() => setMode("existing")}
            />
            Adopt an existing compatible receipt
          </label>
          <label>
            <input
              type="radio"
              name="verificationMode"
              checked={selectedMode === "create"}
              onChange={() => setMode("create")}
            />
            Create a receipt with explicit allocations
          </label>
          <p>
            Creation cannot reuse another operation's receipt key. Pending claims are not income.
          </p>
        </fieldset>
      )}
      <p>
        Pickers show at most 100 records. Use a contextual record link if the needed expectation is
        outside this selection.
      </p>
      {(!verification || selectedMode) && (
        <CommandLoader
          showParentLink={false}
          key={`${session}:${selectedMode}`}
          definition={editor}
          sourceId={target}
          childId={selectedChild}
          revision={state.revision}
          initial={initial}
          choices={state.choices}
          choicesForValues={(values) => ({
            ...state.choices,
            categoryId: (state.choices.categoryId ?? []).filter(
              (choice) =>
                !choice.historical ||
                (values.historicalEntryConfirmed === true &&
                  !!scalar(values.historicalEntryReason, "").trim()),
            ),
          })}
          canSubmit={(values) =>
            verification
              ? !ownerVerificationProblem(values, state.value, selectedMode)
              : definition.formKey === "finance.rent_expectation.synchronize"
                ? confirmedSchedule === scheduleKey(values)
                : definition.formKey === "finance.rent_receipt.create"
                  ? receiptBalance(values).remaining === 0n &&
                    !paymentMethodProblem(values, definition.schema)
                  : definition.formKey === "finance.deposit_credit.create" ||
                      definition.formKey === "finance.deposit_credit.update"
                    ? creditReady(values, confirmedInterest)
                    : definition.formKey === "finance.deposit_deduction_source.add"
                      ? confirmedSource === sourceReviewKey(values)
                      : depositDuplicates(definition.formKey, values, state.children).length > 0
                        ? values.duplicateConfirmed === true
                        : true
          }
          renderContext={(values, locked, onChange) =>
            definition.formKey.startsWith("owner_rent_report.") ? (
              <OwnerReportContext
                values={values}
                report={state.value}
                locked={locked}
                onChange={onChange}
                mode={verification ? selectedMode : undefined}
                editableOwner={["owner_rent_report.create", "owner_rent_report.patch"].includes(
                  definition.formKey,
                )}
              />
            ) : definition.formKey === "finance.rent_expectation.synchronize" ? (
              <RentScheduleContext
                leaseId={target!}
                lease={state.value}
                values={values}
                locked={locked}
                onChange={onChange}
                onConfirm={setConfirmedSchedule}
              />
            ) : definition.formKey.startsWith("finance.prepaid_check.") ? (
              <CheckContext check={selected} lease={state.value} />
            ) : definition.formKey === "finance.expense.create" ? (
              <ExpenseContext
                values={values}
                locked={locked}
                onChange={onChange}
                candidates={expenseCandidates}
              />
            ) : definition.formKey.startsWith("finance.deposit_") ? (
              <>
                <DepositContext
                  formKey={definition.formKey}
                  account={state.value}
                  selected={selected}
                  children={state.children}
                  values={values}
                  locked={locked}
                  onChange={onChange}
                />
                {(definition.formKey === "finance.deposit_credit.create" ||
                  definition.formKey === "finance.deposit_credit.update") && (
                  <InterestCreditReview
                    values={values}
                    locked={locked}
                    onChange={onChange}
                    onConfirm={setConfirmedInterest}
                    confirmed={confirmedInterest}
                  />
                )}
                {definition.formKey === "finance.deposit_deduction_source.add" && (
                  <DeductionSourceReview
                    accountId={target!}
                    values={values}
                    locked={locked}
                    onConfirm={setConfirmedSource}
                    confirmed={confirmedSource}
                  />
                )}
              </>
            ) : definition.formKey === "finance.rent_receipt.create" ? (
              <>
                <ReceiptAllocationContext values={values} />
                <PaymentMethodReview
                  values={values}
                  suggestion={priorReceipt.data ?? state.receiptSuggestion}
                  replacement={!!priorReceipt.data}
                  schema={definition.schema}
                />
              </>
            ) : null
          }
          reviewSource={
            target
              ? async () => {
                  const current = await commandSource(definition, target, selectedChild, leaseId);
                  return {
                    revision: current.revision,
                    value: current.value,
                    relatedRevisions:
                      current.ledgerRevision === undefined
                        ? undefined
                        : { expectedRentLedgerRevision: current.ledgerRevision },
                  };
                }
              : undefined
          }
          checkSource={async (values) => {
            if (verification) {
              const problem = ownerVerificationProblem(values, state.value, selectedMode);
              if (problem) throw new Error(problem);
            }
            if (definition.formKey === "finance.rent_receipt.create") {
              const problem = paymentMethodProblem(values, definition.schema);
              if (problem) throw new Error(problem);
            }
            if (
              definition.formKey === "finance.deposit_deduction_source.add" &&
              confirmedSource !== sourceReviewKey(values)
            )
              throw new Error(
                "Preview and confirm the selected deduction source before attaching it.",
              );
            if (
              (definition.formKey === "finance.deposit_credit.create" ||
                definition.formKey === "finance.deposit_credit.update") &&
              !creditReady(values, confirmedInterest)
            )
              throw new Error(
                "Review the current interest inputs and applied credit; confirm any override reason before saving.",
              );
            if (
              depositDuplicates(definition.formKey, values, state.children).length &&
              values.duplicateConfirmed !== true
            )
              throw new Error(
                "Review the possible duplicate deposit payment and explicitly confirm a separate payment.",
              );
            if (
              definition.formKey === "finance.expense.create" &&
              values.duplicateConfirmed !== true
            ) {
              const reviewed = readResult(
                await api.POST("/api/expenses/duplicate-review", {
                  body: {
                    propertyId: scalar(values.propertyId),
                    paidOn: scalar(values.paidOn),
                    amount: scalar(values.amount),
                    providerPartyId: values.providerPartyId
                      ? scalar(values.providerPartyId)
                      : undefined,
                    payeeName: values.payeeName ? scalar(values.payeeName) : undefined,
                  },
                }),
              );
              setExpenseCandidates(reviewed.candidates);
              if (reviewed.candidates.length)
                throw new Error("Review possible duplicate expenses before recording separately.");
            }
            if (
              definition.formKey === "finance.rent_expectation.synchronize" &&
              confirmedSchedule !== scheduleKey(values)
            )
              throw new Error(
                "Preview and confirm the current rent schedule before synchronizing.",
              );
            if (
              definition.formKey === "finance.rent_receipt.create" &&
              receiptBalance(values).remaining !== 0n
            )
              throw new Error("Receipt and allocated totals must match before recording money.");
            if (
              verification &&
              (!!values.existingReceiptId === !!values.receiptIdempotencyKey ||
                (selectedMode === "existing" &&
                  Array.isArray(values.allocations) &&
                  values.allocations.length))
            )
              throw new Error("Choose exactly one receipt verification mode.");
            if (definition.formKey === "finance.rent_receipt.create" && values.leaseId !== target)
              throw new Error("The payment must use the displayed Lease ledger.");
            if (definition.formKey === "file.upload" && (!values.entityType || !values.entityId))
              throw new Error("Select a record's evidence action first.");
            return Promise.resolve();
          }}
          returnTo={parentTarget}
        />
      )}
    </>
  );
}
