import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "@epm/contracts";
import { workflows, record, scalar, type Workflow } from "@epm/contracts/workflows";
import { useWorkspace } from "../app/workspace-gate";
import { CommandLoader } from "./command";
import { readResult } from "./reads";
import { loadMoneyRecord, MoneyFacts, moneyRecordUrl, type MoneyKind } from "./money-records";

type Source = {
  revision: number;
  value: Record<string, unknown>;
  children: Record<string, unknown>[];
  choices: Record<string, { id: string; label: string }[]>;
  ledgerRevision?: number;
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
    source.choices.leaseTermId = lease.terms.map((term) => ({
      id: term.id,
      label: `${term.effectiveOn} · ${term.paymentFrequency}`,
    }));
    source.choices.expectationId = expectations.items.map((item) => ({
      id: item.id,
      label: `${item.periodStartsOn} – ${item.periodEndsOn} · ${item.outstandingAmountMinor} cents outstanding`,
    }));
    source.choices.payerPartyId = lease.participants.map((item) => ({
      id: item.tenantPartyId,
      label: `${item.tenantPartyId} · ${item.startsOn} – ${item.endsOn ?? "ongoing"}`,
    }));
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
        .filter((item) => !item.voidedAt)
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
        params: { query: { includeArchived: false } },
      }),
    );
    source.choices.categoryId = categories.map((item) => ({
      id: item.id,
      label: item.displayName,
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
  if (source.isPending || (resume && saved.isPending))
    return <p role="status">Loading displayed money source…</p>;
  if (source.error || saved.error)
    return <p role="alert">{source.error?.message ?? saved.error?.message}</p>;
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
    initial.leaseId = target;
    initial.currencyCode = "USD";
    if (selected) {
      initial.amountMinor = selected.outstandingAmountMinor;
      initial.allocations = [
        { expectationId: selected.id, amountMinor: selected.outstandingAmountMinor },
      ];
    }
  }
  if (definition.formKey === "finance.prepaid_check.create" && selected)
    initial.expectationId = selected.id;
  if (definition.formKey === "finance.expense.create")
    Object.assign(initial, { paidByKind: "local_operator", currencyCode: "USD" });
  if (definition.formKey === "finance.deposit_receipt.create")
    Object.assign(initial, { currencyCode: "USD", receivedByKind: "local_operator" });
  if (definition.formKey === "finance.deposit_refund.create") initial.currencyCode = "USD";
  if (definition.formKey === "file.upload")
    Object.assign(initial, {
      entityType: params.get("entityType"),
      entityId: params.get("entityId"),
      purpose: "supporting_document",
    });
  if (state.ledgerRevision !== undefined) initial.expectedRentLedgerRevision = state.ledgerRevision;
  const verification = definition.formKey === "owner_rent_report.verify";
  const selectedMode =
    mode ??
    (saved.data ? (saved.data.payload.existingReceiptId ? "existing" : "create") : undefined);
  if (verification && !saved.data) {
    if (selectedMode === "create") {
      initial.receiptIdempotencyKey = receiptKey;
      initial.allocations = [{}];
    }
  }
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
          key={`${session}:${selectedMode}`}
          definition={editor}
          sourceId={target}
          childId={selectedChild}
          revision={state.revision}
          initial={initial}
          choices={state.choices}
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
          checkSource={(values) => {
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
          returnTo={
            definition.sourceKind === "lease"
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
                : "/money"
          }
        />
      )}
      <Link to="/money">Money workspace</Link>
    </>
  );
}
