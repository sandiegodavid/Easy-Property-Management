import { useId, useRef, useState } from "react";
import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api } from "@epm/contracts";
import type { components } from "@epm/contracts/generated";
import { scalar } from "@epm/contracts/workflows";
import { SourceWorkflowLink as Link } from "../shared/home-navigation";
import { useWorkspace } from "../app/workspace-gate";
import { formatDate, formatUsd } from "../shared/presentation";
import { MutationFailure } from "../shared/mutations";
import { recoveryApi } from "../shared/recovery";
import { cents } from "./money-presentation";
import { dollarCents } from "./receipt-fields";
import { readResult } from "./reads";

type Policy = components["schemas"]["LateFeePolicyResponse"];
type PreviewResponse = components["schemas"]["LateFeePreviewResponse"];
type PreviewItem = components["schemas"]["LateFeePreviewItemResponse"];
type AssessmentSummary = components["schemas"]["LateFeeAssessmentSummaryResponse"];
type AssessmentDetail = components["schemas"]["LateFeeAssessmentDetailResponse"];
type FormulaKind = Policy["formulaKind"];
type CalculationBasis = Policy["calculationBasis"];
type RoundingMode = Policy["roundingMode"];
type PaymentMethodKind = components["schemas"]["RecordLateFeeReceiptInput"]["paymentMethodKind"];

const SETTLEMENT_LABELS: Record<AssessmentSummary["settlementStatus"], string> = {
  unpaid: "Unpaid",
  partially_paid: "Partially paid",
  paid: "Paid",
  waived: "Waived",
  voided: "Voided",
};

const FORMULA_LABELS: Record<FormulaKind, string> = {
  fixed_flat: "Fixed flat fee",
  percentage_once: "Percentage once",
  daily_flat: "Daily flat fee",
  fixed_plus_daily_flat: "Initial flat + daily flat",
};

const BASIS_LABELS: Record<CalculationBasis, string> = {
  unpaid_rent_at_grace_end: "Unpaid rent at grace end",
  current_unpaid_rent: "Current unpaid rent",
  scheduled_rent: "Scheduled rent",
};

const ELIGIBILITY_LABELS: Record<PreviewItem["eligibilityStatus"], string> = {
  eligible: "Eligible",
  no_applicable_policy: "No applicable policy",
  excluded_prorated_period: "Prorated period excluded",
  within_grace_period: "Within grace period",
  paid_in_full: "Paid in full",
  below_minimum_threshold: "Below minimum threshold",
  already_assessed: "Already assessed",
  already_assessed_through_date: "Already assessed through date",
  max_accrual_days_reached: "Max accrual days reached",
  period_cap_reached: "Period cap reached",
  calculated_zero: "Calculated $0.00",
};

const PAYMENT_METHODS: { value: PaymentMethodKind; label: string }[] = [
  { value: "check", label: "Check" },
  { value: "bank_transfer", label: "Bank transfer" },
  { value: "automatic_bank_payment", label: "Automatic bank payment (external)" },
  { value: "online_payment", label: "Online payment" },
  { value: "cash", label: "Cash" },
  { value: "other", label: "Other" },
];

const LATE_FEE_RECOVERY_FORM_KEYS = new Set([
  "finance.late_fee_policy.create",
  "finance.late_fee_policy.void",
  "finance.late_fee_assessment.create",
  "finance.late_fee_assessment.waive",
  "finance.late_fee_assessment.void",
  "finance.late_fee_receipt.create",
  "finance.late_fee_receipt.void",
  "finance.combined_receipt.create",
]);

interface ActiveAttempt {
  recordId: string;
  revision: number;
  attemptKey: string;
}

async function fetchAllRecoveryRecords(
  signal?: AbortSignal,
): Promise<components["schemas"]["RecoveryPage"]["items"]> {
  const all: components["schemas"]["RecoveryPage"]["items"] = [];
  let cursor: string | undefined;
  for (let pageCount = 0; pageCount < 20; pageCount += 1) {
    const page: components["schemas"]["RecoveryPage"] = readResult(
      await api.GET("/api/operator/recovery", {
        signal,
        params: { query: { limit: 50, cursor } },
      }),
    );
    all.push(...page.items);
    if (!page.nextCursor) break;
    cursor = page.nextCursor;
  }
  return all;
}

function useOpsRecoveryCommand(
  leaseId: string,
  formKey: components["schemas"]["RecoveryInput"]["formKey"],
  label: string,
  onRecovered: () => void,
) {
  const { scope } = useWorkspace();
  const queryClient = useQueryClient();
  const activeAttemptRef = useRef<ActiveAttempt | null>(null);
  const [status, setStatus] = useState<"editing" | "submitting" | "rejected" | "outcome_unknown">(
    "editing",
  );
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const recoveryQuery = useQuery({
    queryKey: scope.key("lease-late-fee-recovery", leaseId),
    retry: false,
    queryFn: ({ signal }) => fetchAllRecoveryRecords(signal),
  });

  const unresolvedAttempt =
    (recoveryQuery.data ?? []).find(
      (item) =>
        item.sourceKind === "lease" &&
        item.sourceId === leaseId &&
        item.formKey === formKey &&
        item.status === "outcome_unknown",
    ) ?? null;

  const isOutcomeUnknown = status === "outcome_unknown" || unresolvedAttempt !== null;
  const recoveryCheckFailed = Boolean(recoveryQuery.error);

  async function execute<T>({
    expectedRevision,
    recoveryPayload,
    dispatch,
  }: {
    expectedRevision: number;
    recoveryPayload: Record<string, unknown>;
    dispatch: (idempotencyKey: string) => Promise<{ data?: T; error?: unknown }>;
  }): Promise<{ ok: true; data?: T } | { ok: false; error?: unknown }> {
    if (status === "outcome_unknown" || activeAttemptRef.current !== null || unresolvedAttempt) {
      setErrorMessage(
        `A previous "${label}" submission has an unknown outcome. Check the committed outcome before submitting again.`,
      );
      return { ok: false };
    }
    // Exhaust all pages of live OPS-001 state before starting a new attempt; fail closed on error.
    try {
      const liveItems = await fetchAllRecoveryRecords();
      const livePending = liveItems.find(
        (item) =>
          item.sourceKind === "lease" &&
          item.sourceId === leaseId &&
          item.formKey === formKey &&
          item.status === "outcome_unknown",
      );
      if (livePending) {
        void queryClient.invalidateQueries({
          queryKey: scope.key("lease-late-fee-recovery", leaseId),
        });
        setStatus("outcome_unknown");
        setErrorMessage(
          `A previous "${label}" submission has an unknown outcome. Check the committed outcome before submitting again.`,
        );
        return { ok: false };
      }
    } catch {
      setStatus("rejected");
      setErrorMessage(
        "Unable to verify whether a previous submission is still pending. Retry once recovery checks are available.",
      );
      return { ok: false };
    }
    setStatus("submitting");
    setErrorMessage(null);
    const recordId = crypto.randomUUID();
    const attemptKey = crypto.randomUUID();
    let prepared: components["schemas"]["RecoveryResponse"];
    try {
      const saved = await recoveryApi.save(recordId, {
        formKey,
        schemaVersion: 1,
        sourceKind: "lease",
        sourceId: leaseId,
        baseSourceRevision: String(expectedRevision),
        expectedRevision: 0,
        idempotencyKey: crypto.randomUUID(),
        payload: recoveryPayload,
      });
      prepared = await recoveryApi.prepare(recordId, {
        expectedRevision: saved.revision,
        idempotencyKey: crypto.randomUUID(),
        attemptKey,
      });
    } catch (error) {
      setStatus("rejected");
      setErrorMessage(extractApiError(error));
      return { ok: false, error };
    }

    const dispatchedKey = prepared.attemptKey ?? attemptKey;
    activeAttemptRef.current = {
      recordId: prepared.id,
      revision: prepared.revision,
      attemptKey: dispatchedKey,
    };
    void queryClient.invalidateQueries({ queryKey: scope.key("lease-late-fee-recovery", leaseId) });

    try {
      const response = await dispatch(dispatchedKey);
      if (response.error) {
        try {
          const editable = await recoveryApi.returnToEditing(prepared.id, {
            expectedRevision: prepared.revision,
            idempotencyKey: crypto.randomUUID(),
          });
          await recoveryApi.discard(prepared.id, {
            expectedRevision: editable.revision,
            idempotencyKey: crypto.randomUUID(),
          });
        } catch {
          // Non-fatal cleanup; server remains authoritative.
        }
        activeAttemptRef.current = null;
        void queryClient.invalidateQueries({
          queryKey: scope.key("lease-late-fee-recovery", leaseId),
        });
        setStatus("rejected");
        setErrorMessage(extractApiError(response.error));
        return { ok: false, error: response.error };
      }
      try {
        await recoveryApi.reconcile(prepared.id, {
          expectedRevision: prepared.revision,
          idempotencyKey: crypto.randomUUID(),
        });
      } catch {
        // Finance already committed; OPS record will reconcile cleanly if checked later.
      }
      activeAttemptRef.current = null;
      void queryClient.invalidateQueries({
        queryKey: scope.key("lease-late-fee-recovery", leaseId),
      });
      setStatus("editing");
      setErrorMessage(null);
      return { ok: true, data: response.data };
    } catch {
      setStatus("outcome_unknown");
      setErrorMessage(
        `The response for "${label}" was lost. Check the committed outcome before retrying to avoid duplicates.`,
      );
      void queryClient.invalidateQueries({
        queryKey: scope.key("lease-late-fee-recovery", leaseId),
      });
      return { ok: false };
    }
  }

  async function checkOutcome() {
    const active =
      activeAttemptRef.current ??
      (unresolvedAttempt
        ? {
            recordId: unresolvedAttempt.id,
            revision: unresolvedAttempt.revision,
            attemptKey: "",
          }
        : null);
    if (!active) return;
    setErrorMessage(null);
    try {
      const reconciled = await recoveryApi.reconcile(active.recordId, {
        expectedRevision: active.revision,
        idempotencyKey: crypto.randomUUID(),
      });
      if (reconciled.status === "reconciled") {
        activeAttemptRef.current = null;
        setStatus("editing");
        void queryClient.invalidateQueries({
          queryKey: scope.key("lease-late-fee-recovery", leaseId),
        });
        onRecovered();
        return;
      }
      if (reconciled.status === "active" || reconciled.status === "outcome_unknown") {
        const editable =
          reconciled.status === "outcome_unknown"
            ? await recoveryApi.returnToEditing(active.recordId, {
                expectedRevision: reconciled.revision,
                idempotencyKey: crypto.randomUUID(),
              })
            : reconciled;
        await recoveryApi.discard(active.recordId, {
          expectedRevision: editable.revision,
          idempotencyKey: crypto.randomUUID(),
        });
        activeAttemptRef.current = null;
        setStatus("editing");
        void queryClient.invalidateQueries({
          queryKey: scope.key("lease-late-fee-recovery", leaseId),
        });
        setErrorMessage(
          "No committed operation was found for this attempt. You may safely retry or cancel.",
        );
        return;
      }
      activeAttemptRef.current = {
        ...active,
        revision: reconciled.revision,
      };
      setErrorMessage("Outcome is still pending reconciliation. Try checking again.");
    } catch (error) {
      if (error instanceof MutationFailure && error.status === 409) {
        try {
          const editable = await recoveryApi.returnToEditing(active.recordId, {
            expectedRevision: active.revision,
            idempotencyKey: crypto.randomUUID(),
          });
          await recoveryApi.discard(active.recordId, {
            expectedRevision: editable.revision,
            idempotencyKey: crypto.randomUUID(),
          });
          activeAttemptRef.current = null;
          setStatus("editing");
          void queryClient.invalidateQueries({
            queryKey: scope.key("lease-late-fee-recovery", leaseId),
          });
          setErrorMessage(
            "No committed operation was found for this attempt. You may safely retry or cancel.",
          );
          return;
        } catch {
          // Fall through to generic connectivity error.
        }
      }
      setErrorMessage("Could not reach the server to check the committed outcome. Try again.");
    }
  }

  return {
    status: isOutcomeUnknown ? ("outcome_unknown" as const) : status,
    unresolvedAttempt,
    recoveryCheckFailed,
    retryRecoveryCheck: () => void recoveryQuery.refetch(),
    errorMessage:
      errorMessage ??
      (unresolvedAttempt
        ? `A previous "${label}" submission has an unknown outcome. Check the committed outcome before submitting again.`
        : recoveryCheckFailed
          ? "Unable to verify pending recovery operations. Retry before submitting."
          : null),
    setErrorMessage,
    execute,
    checkOutcome,
  };
}

function usd(minor: number): string {
  return formatUsd(cents(minor));
}

function percentToBps(text: string): number | undefined {
  const trimmed = text.trim();
  if (!/^\d+(?:\.\d{0,2})?$/.test(trimmed)) return undefined;
  const [whole, frac = ""] = trimmed.split(".");
  const bps = Number(whole) * 100 + Number(frac.padEnd(2, "0"));
  return Number.isSafeInteger(bps) && bps >= 1 && bps <= 10_000 ? bps : undefined;
}

function formulaSummary(policy: Policy): string {
  if (policy.formulaKind === "fixed_flat" && policy.flatAmountMinor !== null) {
    return `${usd(policy.flatAmountMinor)} flat`;
  }
  if (policy.formulaKind === "percentage_once" && policy.percentageBps !== null) {
    return `${(policy.percentageBps / 100).toFixed(2)}% of ${BASIS_LABELS[policy.calculationBasis].toLowerCase()}`;
  }
  if (policy.formulaKind === "daily_flat" && policy.dailyAmountMinor !== null) {
    return `${usd(policy.dailyAmountMinor)}/day`;
  }
  if (
    policy.formulaKind === "fixed_plus_daily_flat" &&
    policy.flatAmountMinor !== null &&
    policy.dailyAmountMinor !== null
  ) {
    return `${usd(policy.flatAmountMinor)} initial + ${usd(policy.dailyAmountMinor)}/day`;
  }
  return FORMULA_LABELS[policy.formulaKind];
}

function extractApiError(error: unknown): string {
  if (error && typeof error === "object") {
    const detail = (error as { detail?: unknown }).detail;
    if (detail && typeof detail === "object" && "message" in detail) {
      return String(detail.message);
    }
    if (typeof detail === "string") return detail;
    if ("message" in error && typeof error.message === "string") {
      return (error as { message: string }).message;
    }
  }
  return "The request could not be completed. Retry or check the recorded outcome.";
}

function isDuplicateReceiptError(error: unknown): boolean {
  if (!error || typeof error !== "object") return false;
  const detail = (error as { detail?: unknown }).detail;
  if (detail && typeof detail === "object") {
    const code = "code" in detail ? String(detail.code) : "";
    const msg = "message" in detail ? String(detail.message).toLowerCase() : "";
    if (code === "likely_duplicate_receipt" || msg.includes("duplicate")) return true;
  }
  return false;
}

export function LeasePendingRecoveryBanner({
  leaseId,
  onRecovered,
}: {
  leaseId: string;
  onRecovered: () => void;
}) {
  const { scope } = useWorkspace();
  const queryClient = useQueryClient();
  const [message, setMessage] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);

  const recoveryQuery = useQuery({
    queryKey: scope.key("lease-late-fee-recovery", leaseId),
    retry: false,
    queryFn: ({ signal }) => fetchAllRecoveryRecords(signal),
  });

  const pendingOps = (recoveryQuery.data ?? []).filter(
    (item) =>
      item.sourceKind === "lease" &&
      item.sourceId === leaseId &&
      LATE_FEE_RECOVERY_FORM_KEYS.has(item.formKey) &&
      item.status === "outcome_unknown",
  );

  if (recoveryQuery.error) {
    return (
      <div className="record-detail-panel" role="alert" aria-label="Pending operation recovery">
        <h4>Pending late-fee operation recovery unavailable</h4>
        <p>
          Pending recovery operations could not be verified ({recoveryQuery.error.message}). Retry
          before submitting new late-fee commands.
        </p>
        <button type="button" onClick={() => void recoveryQuery.refetch()}>
          Retry recovery check
        </button>
      </div>
    );
  }

  if (pendingOps.length === 0) return null;

  async function verifyOp(item: { id: string; revision: number; formKey: string }) {
    setChecking(true);
    setMessage(null);
    try {
      const reconciled = await recoveryApi.reconcile(item.id, {
        expectedRevision: item.revision,
        idempotencyKey: crypto.randomUUID(),
      });
      if (reconciled.status === "reconciled") {
        void queryClient.invalidateQueries({
          queryKey: scope.key("lease-late-fee-recovery", leaseId),
        });
        setMessage(`Recovered committed operation (${item.formKey}).`);
        onRecovered();
      } else if (reconciled.status === "active" || reconciled.status === "outcome_unknown") {
        const editable =
          reconciled.status === "outcome_unknown"
            ? await recoveryApi.returnToEditing(item.id, {
                expectedRevision: reconciled.revision,
                idempotencyKey: crypto.randomUUID(),
              })
            : reconciled;
        await recoveryApi.discard(item.id, {
          expectedRevision: editable.revision,
          idempotencyKey: crypto.randomUUID(),
        });
        void queryClient.invalidateQueries({
          queryKey: scope.key("lease-late-fee-recovery", leaseId),
        });
        setMessage(
          `Operation (${item.formKey}) was not committed on the server and has been cleared. You may submit again.`,
        );
      } else {
        void queryClient.invalidateQueries({
          queryKey: scope.key("lease-late-fee-recovery", leaseId),
        });
        setMessage("Operation outcome is still pending. Try checking again.");
      }
    } catch (error) {
      if (error instanceof MutationFailure && error.status === 409) {
        try {
          const editable = await recoveryApi.returnToEditing(item.id, {
            expectedRevision: item.revision,
            idempotencyKey: crypto.randomUUID(),
          });
          await recoveryApi.discard(item.id, {
            expectedRevision: editable.revision,
            idempotencyKey: crypto.randomUUID(),
          });
          void queryClient.invalidateQueries({
            queryKey: scope.key("lease-late-fee-recovery", leaseId),
          });
          setMessage(
            `Operation (${item.formKey}) was not committed on the server and has been cleared. You may submit again.`,
          );
          return;
        } catch {
          // Fall through to generic error.
        }
      }
      setMessage("Unable to verify operation outcome right now. Try again.");
    } finally {
      setChecking(false);
    }
  }

  return (
    <div className="record-detail-panel" role="alert" aria-label="Pending operation recovery">
      <h4>Pending late-fee operation recovery</h4>
      {message && <p role="status">{message}</p>}
      {pendingOps.map((item) => (
        <div key={item.id} className="child-record-card">
          <p>
            Previous <strong>{item.formKey}</strong> submission did not receive a final response.
            Check whether it committed before submitting again.
          </p>
          <div className="form-actions">
            <button type="button" disabled={checking} onClick={() => void verifyOp(item)}>
              {checking ? "Checking…" : "Check committed outcome"}
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}

export function LeaseLateFeesSection({
  leaseId,
  leaseStatus,
}: {
  leaseId: string;
  leaseStatus: string;
}) {
  const { scope } = useWorkspace();
  const queryClient = useQueryClient();
  const [showPolicyForm, setShowPolicyForm] = useState(false);
  const [supersedePolicyId, setSupersedePolicyId] = useState<string | null>(null);
  const [asOfDate, setAsOfDate] = useState("");
  const [selectedExpectationId, setSelectedExpectationId] = useState("");
  const [preview, setPreview] = useState<PreviewResponse | null>(null);
  const [previewItems, setPreviewItems] = useState<PreviewItem[]>([]);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [previewPending, setPreviewPending] = useState(false);
  const [showCombinedForm, setShowCombinedForm] = useState(false);
  const [replacingAssessment, setReplacingAssessment] = useState<{
    id: string;
    rentExpectationId: string;
    asOfDate: string;
  } | null>(null);

  const previewSeqRef = useRef(0);
  const previewAbortRef = useRef<AbortController | null>(null);

  const policiesQuery = useQuery({
    queryKey: scope.key("lease-late-fee-policies", leaseId),
    retry: false,
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/leases/{lease_id}/late-fee-policies", {
          signal,
          params: { path: { lease_id: leaseId } },
        }),
      ),
  });

  const assessmentsQuery = useQuery({
    queryKey: scope.key("lease-late-fee-assessments", leaseId),
    retry: false,
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/leases/{lease_id}/late-fee-assessments", {
          signal,
          params: { path: { lease_id: leaseId }, query: { includeVoided: true, pageSize: 50 } },
        }),
      ),
  });

  const expectationsQuery = useInfiniteQuery({
    queryKey: scope.key("lease-late-fee-preview-periods", leaseId),
    initialPageParam: null as string | null,
    retry: false,
    queryFn: async ({ pageParam, signal }) =>
      readResult(
        await api.GET("/api/rent-expectations", {
          signal,
          params: { query: { leaseId, pageSize: 50, cursor: pageParam ?? undefined } },
        }),
      ),
    getNextPageParam: (page) => page.nextCursor ?? undefined,
  });

  const invalidatePreview = () => {
    previewSeqRef.current += 1;
    previewAbortRef.current?.abort();
    previewAbortRef.current = null;
    setPreview(null);
    setPreviewItems([]);
    setPreviewPending(false);
  };

  const invalidateAll = () => {
    invalidatePreview();
    setReplacingAssessment(null);
    void queryClient.invalidateQueries({ queryKey: scope.key("lease-late-fee-policies", leaseId) });
    void queryClient.invalidateQueries({
      queryKey: scope.key("lease-late-fee-assessments", leaseId),
    });
    void queryClient.invalidateQueries({ queryKey: scope.key("late-fee-assessment-detail") });
    void queryClient.invalidateQueries({ queryKey: scope.key("portfolio-late-fee-assessments") });
  };

  const policies = policiesQuery.data?.items ?? [];
  const activePolicy = policies.find((item) => item.status === "active") ?? null;
  const historicalPolicies = policies.filter((item) => item.status !== "active");
  const revision = policiesQuery.data?.rentLedgerRevision ?? 0;
  const assessments = assessmentsQuery.data?.items ?? [];
  const unpaidAssessments = assessments.filter(
    (item) => item.remainingBalanceMinor > 0 && item.settlementStatus !== "voided",
  );
  const allPeriods = (expectationsQuery.data?.pages ?? [])
    .flatMap((page) => page.items)
    .filter((period) => !period.voidedAt);

  async function runPreview(options?: {
    cursor?: string | null;
    overrideAsOfDate?: string;
    overrideExpectationId?: string;
    append?: boolean;
  }) {
    previewAbortRef.current?.abort();
    const controller = new AbortController();
    previewAbortRef.current = controller;
    const seq = ++previewSeqRef.current;

    const targetDate = options?.overrideAsOfDate ?? asOfDate;
    const targetExp = options?.overrideExpectationId ?? selectedExpectationId;
    setPreviewPending(true);
    setPreviewError(null);
    try {
      const response = await api.POST("/api/leases/{lease_id}/late-fees/preview", {
        signal: controller.signal,
        params: { path: { lease_id: leaseId } },
        body: {
          asOfDate: targetDate || null,
          rentExpectationId: targetExp || null,
          cursor: options?.cursor ?? null,
        },
      });
      if (seq !== previewSeqRef.current) return;
      if (response.error || !response.data) {
        if (!options?.append) {
          setPreview(null);
          setPreviewItems([]);
        }
        setPreviewError(extractApiError(response.error));
      } else {
        if (
          options?.append &&
          preview &&
          response.data.rentLedgerRevision !== preview.rentLedgerRevision
        ) {
          setPreview(null);
          setPreviewItems([]);
          setPreviewError(
            "The rent ledger changed while loading more preview periods. Run Preview eligible late fees again to refresh all periods.",
          );
          return;
        }
        setPreview(response.data);
        setPreviewItems((prev) =>
          options?.append ? [...prev, ...response.data.items] : response.data.items,
        );
        if (!targetDate) setAsOfDate(response.data.asOfDate);
      }
    } catch (error) {
      if (seq !== previewSeqRef.current) return;
      if (!options?.append) {
        setPreview(null);
        setPreviewItems([]);
      }
      setPreviewError(extractApiError(error));
    } finally {
      if (seq === previewSeqRef.current) {
        setPreviewPending(false);
      }
    }
  }

  function startReplacementPreview(target: {
    id: string;
    rentExpectationId: string;
    asOfDate: string;
  }) {
    setReplacingAssessment(target);
    setAsOfDate(target.asOfDate);
    setSelectedExpectationId(target.rentExpectationId);
    void runPreview({
      overrideAsOfDate: target.asOfDate,
      overrideExpectationId: target.rentExpectationId,
    });
  }

  return (
    <section className="lease-detail-section" aria-label="Late fees">
      <div className="child-record-heading">
        <h3>Late fees</h3>
        <Link to={`/money?tab=late_fees&leaseId=${leaseId}`}>Open in Money → Late fees</Link>
      </div>

      <LeasePendingRecoveryBanner leaseId={leaseId} onRecovered={invalidateAll} />

      {/* Policy panel */}
      <div className="record-detail-panel" aria-label="Late-fee policy">
        <div className="child-record-heading">
          <h4>Late-fee policy</h4>
          {leaseStatus !== "void" && !showPolicyForm && (
            <button
              type="button"
              onClick={() => {
                setSupersedePolicyId(activePolicy?.id ?? null);
                setShowPolicyForm(true);
              }}
            >
              {activePolicy ? "Configure new policy version" : "Configure late-fee policy"}
            </button>
          )}
        </div>
        {policiesQuery.isPending && <p role="status">Loading late-fee policy…</p>}
        {policiesQuery.error && (
          <div role="alert">
            <p>Late-fee policy is unavailable: {policiesQuery.error.message}</p>
            <button type="button" onClick={() => void policiesQuery.refetch()}>
              Retry
            </button>
          </div>
        )}
        {policiesQuery.data && !activePolicy && !showPolicyForm && (
          <p>
            <strong>No late-fee policy configured.</strong> EPM does not apply default late-fee
            rates. Configure and confirm a policy citing the lease clause before previewing fees.
          </p>
        )}
        {activePolicy && (
          <article className="child-record-card">
            <p>
              <strong>Version {activePolicy.versionNumber}</strong> · Active ·{" "}
              {formulaSummary(activePolicy)}
            </p>
            <dl>
              <div>
                <dt>Contractual basis</dt>
                <dd>{activePolicy.ruleBasis}</dd>
              </div>
              <div>
                <dt>Effective window</dt>
                <dd>
                  {formatDate(activePolicy.effectiveOn)} –{" "}
                  {activePolicy.endsOn ? formatDate(activePolicy.endsOn) : "Ongoing"}
                </dd>
              </div>
              <div>
                <dt>Grace period</dt>
                <dd>{activePolicy.gracePeriodDays} property-local calendar day(s)</dd>
              </div>
              <div>
                <dt>Calculation basis &amp; rounding</dt>
                <dd>
                  {BASIS_LABELS[activePolicy.calculationBasis]} ·{" "}
                  {activePolicy.roundingMode === "half_up" ? "Half-up" : "Floor"}
                </dd>
              </div>
              <div>
                <dt>Prorated periods</dt>
                <dd>{activePolicy.appliesToProratedPeriods ? "Included" : "Excluded"}</dd>
              </div>
            </dl>
            <VoidPolicyControl
              leaseId={leaseId}
              policy={activePolicy}
              expectedRevision={revision}
              onCommitted={invalidateAll}
            />
          </article>
        )}
        {showPolicyForm && (
          <ConfigurePolicyForm
            leaseId={leaseId}
            expectedRevision={revision}
            supersedesPolicyVersionId={supersedePolicyId}
            onCancel={() => setShowPolicyForm(false)}
            onCommitted={() => {
              setShowPolicyForm(false);
              invalidateAll();
            }}
          />
        )}
        {historicalPolicies.length > 0 && (
          <details>
            <summary>Policy history ({historicalPolicies.length})</summary>
            {historicalPolicies.map((policy) => (
              <article className="child-record-card" key={policy.id}>
                <p>
                  <strong>Version {policy.versionNumber}</strong> · {policy.status} ·{" "}
                  {formulaSummary(policy)} · {formatDate(policy.effectiveOn)} –{" "}
                  {policy.endsOn ? formatDate(policy.endsOn) : "Ongoing"}
                </p>
                <p>{policy.ruleBasis}</p>
                {policy.voidReason && <p>Void reason: {policy.voidReason}</p>}
              </article>
            ))}
          </details>
        )}
      </div>

      {/* Calculation preview & review panel */}
      <div className="record-detail-panel" aria-label="Late-fee preview">
        <h4>Calculation preview &amp; review</h4>
        <p>
          <strong>Preview only — not an assessed charge.</strong> Previews create no debt or audit
          entries. Editing the date invalidates an active preview until refreshed.
        </p>
        {replacingAssessment && (
          <div className="child-record-card" role="status">
            <p>
              <strong>Replacing voided assessment</strong> for rent period{" "}
              <code>{replacingAssessment.rentExpectationId.slice(0, 8)}</code>. Review the fresh
              preview and confirm assessment below to link the replacement.
            </p>
            <button type="button" onClick={() => setReplacingAssessment(null)}>
              Cancel replacement link
            </button>
          </div>
        )}
        <div className="late-fee-preview-controls">
          <label>
            Review as-of date (property-local, optional)
            <input
              type="date"
              value={asOfDate}
              onChange={(event) => {
                setAsOfDate(event.target.value);
                invalidatePreview();
              }}
            />
          </label>
          <label>
            Specific rent period (optional)
            <select
              value={selectedExpectationId}
              onChange={(event) => {
                setSelectedExpectationId(event.target.value);
                invalidatePreview();
              }}
            >
              <option value="">All open or late-paid candidate periods</option>
              {allPeriods.map((period) => (
                <option key={period.id} value={period.id}>
                  Due {formatDate(period.dueOn)} ({formatDate(period.periodStartsOn)} –{" "}
                  {formatDate(period.periodEndsOn)})
                </option>
              ))}
            </select>
          </label>
          {expectationsQuery.hasNextPage && (
            <button
              type="button"
              disabled={expectationsQuery.isFetchingNextPage}
              onClick={() => void expectationsQuery.fetchNextPage()}
            >
              {expectationsQuery.isFetchingNextPage ? "Loading periods…" : "Load more rent periods"}
            </button>
          )}
          <button type="button" disabled={previewPending} onClick={() => void runPreview()}>
            {previewPending ? "Calculating preview…" : "Preview eligible late fees"}
          </button>
        </div>
        {previewError && <p role="alert">Preview unavailable: {previewError}</p>}
        {preview && (
          <div className="late-fee-preview-results">
            <p>
              Property time zone: <strong>{preview.timeZone}</strong> · As-of date:{" "}
              <strong>{formatDate(preview.asOfDate)}</strong>
              {preview.futureProjection ? " · Future projection (preview only)" : ""}
            </p>
            {preview.rentLedgerRevision !== revision && (
              <p role="alert">
                The rent ledger changed after this preview was captured. Refresh the preview before
                assessing.
              </p>
            )}
            {previewItems.length === 0 && (
              <p>No open or late-paid candidate rent periods found for this lease.</p>
            )}
            {previewItems.map((item) => (
              <PreviewPeriodRow
                key={item.rentExpectationId}
                leaseId={leaseId}
                preview={preview}
                currentRevision={revision}
                item={item}
                replacesAssessmentId={
                  replacingAssessment &&
                  replacingAssessment.rentExpectationId === item.rentExpectationId
                    ? replacingAssessment.id
                    : null
                }
                onAssessed={invalidateAll}
              />
            ))}
            {preview.nextCursor && (
              <button
                type="button"
                disabled={previewPending}
                onClick={() => void runPreview({ cursor: preview.nextCursor, append: true })}
              >
                {previewPending ? "Loading more…" : "Load next preview periods"}
              </button>
            )}
          </div>
        )}
      </div>

      {/* Assessed late fees list */}
      <div className="record-detail-panel" aria-label="Assessed late fees">
        <div className="child-record-heading">
          <h4>Assessed late fees</h4>
          {unpaidAssessments.length > 0 && !showCombinedForm && (
            <button type="button" onClick={() => setShowCombinedForm(true)}>
              Record combined rent + late-fee payment
            </button>
          )}
        </div>
        {showCombinedForm && (
          <CombinedReceiptForm
            leaseId={leaseId}
            expectedRevision={revision}
            onCancel={() => setShowCombinedForm(false)}
            onCommitted={() => {
              setShowCombinedForm(false);
              invalidateAll();
            }}
          />
        )}
        {assessmentsQuery.isPending && <p role="status">Loading assessed late fees…</p>}
        {assessmentsQuery.error && (
          <div role="alert">
            <p>Assessed late fees are unavailable: {assessmentsQuery.error.message}</p>
            <button type="button" onClick={() => void assessmentsQuery.refetch()}>
              Retry
            </button>
          </div>
        )}
        {assessmentsQuery.data && assessments.length === 0 && (
          <p>No late fees have been assessed for this lease.</p>
        )}
        {assessments.length > 0 && (
          <p className="record-detail-note">
            Click anywhere on an item’s summary bar to expand or collapse its details.
          </p>
        )}
        {assessments.map((item) => (
          <AssessedLateFeeRow
            key={item.id}
            item={item}
            expectedRevision={revision}
            onMutated={invalidateAll}
            onStartReplacement={startReplacementPreview}
          />
        ))}
      </div>
    </section>
  );
}

function ConfigurePolicyForm({
  leaseId,
  expectedRevision,
  supersedesPolicyVersionId,
  onCancel,
  onCommitted,
}: {
  leaseId: string;
  expectedRevision: number;
  supersedesPolicyVersionId: string | null;
  onCancel: () => void;
  onCommitted: () => void;
}) {
  const formId = useId();
  const recovery = useOpsRecoveryCommand(
    leaseId,
    "finance.late_fee_policy.create",
    "Configure late-fee policy",
    onCommitted,
  );
  const [effectiveOn, setEffectiveOn] = useState("");
  const [endsOn, setEndsOn] = useState("");
  const [ruleBasis, setRuleBasis] = useState("");
  const [gracePeriodDays, setGracePeriodDays] = useState("5");
  const [calculationBasis, setCalculationBasis] = useState<CalculationBasis>(
    "unpaid_rent_at_grace_end",
  );
  const [formulaKind, setFormulaKind] = useState<FormulaKind>("fixed_flat");
  const [flatDollars, setFlatDollars] = useState("50.00");
  const [percentageText, setPercentageText] = useState("5.00");
  const [dailyDollars, setDailyDollars] = useState("10.00");
  const [maxAccrualDays, setMaxAccrualDays] = useState("10");
  const [capDollars, setCapDollars] = useState("");
  const [minDollars, setMinDollars] = useState("");
  const [thresholdDollars, setThresholdDollars] = useState("0.00");
  const [roundingMode, setRoundingMode] = useState<RoundingMode>("half_up");
  const [appliesToProrated, setAppliesToProrated] = useState(false);
  const [notes, setNotes] = useState("");
  const [confirmed, setConfirmed] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    recovery.setErrorMessage(null);
    if (!effectiveOn || !ruleBasis.trim()) {
      recovery.setErrorMessage("Effective date and contractual rule basis are required.");
      return;
    }
    if (!confirmed) {
      recovery.setErrorMessage("Explicit operator confirmation is required before saving.");
      return;
    }
    const flatMinor =
      formulaKind === "fixed_flat" || formulaKind === "fixed_plus_daily_flat"
        ? dollarCents(flatDollars)
        : null;
    const pctBps = formulaKind === "percentage_once" ? percentToBps(percentageText) : null;
    const dailyMinor =
      formulaKind === "daily_flat" || formulaKind === "fixed_plus_daily_flat"
        ? dollarCents(dailyDollars)
        : null;
    const maxDays =
      (formulaKind === "daily_flat" || formulaKind === "fixed_plus_daily_flat") &&
      maxAccrualDays.trim()
        ? Number(maxAccrualDays)
        : null;
    const capMinor = capDollars.trim() ? dollarCents(capDollars) : null;
    const minMinor = minDollars.trim() ? dollarCents(minDollars) : null;
    const thresholdMinor = thresholdDollars.trim() ? dollarCents(thresholdDollars) : 0;

    if (
      flatMinor === undefined ||
      pctBps === undefined ||
      dailyMinor === undefined ||
      capMinor === undefined ||
      minMinor === undefined ||
      thresholdMinor === undefined
    ) {
      recovery.setErrorMessage("Check numeric fee amounts and percentage (max 2 decimal places).");
      return;
    }

    const payloadBody = {
      expectedRevision,
      effectiveOn,
      endsOn: endsOn || null,
      leaseTermId: null,
      ruleBasis: ruleBasis.trim(),
      gracePeriodDays: Number(gracePeriodDays),
      calculationBasis,
      formulaKind,
      flatAmountMinor: flatMinor,
      percentageBps: pctBps,
      dailyAmountMinor: dailyMinor,
      maxAccrualDays: maxDays,
      perPeriodCapMinor: capMinor,
      perPeriodMinMinor: minMinor,
      minimumUnpaidThresholdMinor: thresholdMinor,
      roundingMode,
      appliesToProratedPeriods: appliesToProrated,
      supersedesPolicyVersionId,
      notes: notes.trim() || null,
      operatorConfirmed: true,
    };
    const result = await recovery.execute({
      expectedRevision,
      recoveryPayload: payloadBody,
      dispatch: (idempotencyKey) =>
        api.POST("/api/leases/{lease_id}/late-fee-policies", {
          params: { path: { lease_id: leaseId } },
          body: { ...payloadBody, idempotencyKey },
        }),
    });
    if (result.ok) onCommitted();
  }

  return (
    <form
      id={formId}
      className="child-record-card"
      aria-label="Configure late-fee policy"
      onSubmit={(event) => void submit(event)}
    >
      <h5>
        {supersedesPolicyVersionId
          ? "Configure new late-fee policy version (supersedes current active version)"
          : "Configure late-fee policy"}
      </h5>
      {recovery.errorMessage && <p role="alert">{recovery.errorMessage}</p>}
      <label>
        Effective date (required)
        <input
          type="date"
          required
          value={effectiveOn}
          onChange={(e) => setEffectiveOn(e.target.value)}
        />
      </label>
      <label>
        End date (optional, exclusive)
        <input type="date" value={endsOn} onChange={(e) => setEndsOn(e.target.value)} />
      </label>
      <label>
        Contractual rule basis (required)
        <input
          type="text"
          required
          maxLength={500}
          placeholder="e.g. Lease Section 5(b), signed 2026-01-15"
          value={ruleBasis}
          onChange={(e) => setRuleBasis(e.target.value)}
        />
      </label>
      <label>
        Grace period days (0–60, required)
        <input
          type="number"
          min={0}
          max={60}
          required
          value={gracePeriodDays}
          onChange={(e) => setGracePeriodDays(e.target.value)}
        />
      </label>
      <label>
        Calculation basis (required)
        <select
          value={calculationBasis}
          onChange={(e) => setCalculationBasis(e.target.value as CalculationBasis)}
        >
          {Object.entries(BASIS_LABELS).map(([val, label]) => (
            <option key={val} value={val}>
              {label}
            </option>
          ))}
        </select>
      </label>
      <label>
        Formula kind (required)
        <select value={formulaKind} onChange={(e) => setFormulaKind(e.target.value as FormulaKind)}>
          {Object.entries(FORMULA_LABELS).map(([val, label]) => (
            <option key={val} value={val}>
              {label}
            </option>
          ))}
        </select>
      </label>
      {(formulaKind === "fixed_flat" || formulaKind === "fixed_plus_daily_flat") && (
        <label>
          Flat amount USD (required)
          <input
            type="text"
            inputMode="decimal"
            required
            value={flatDollars}
            onChange={(e) => setFlatDollars(e.target.value)}
          />
        </label>
      )}
      {formulaKind === "percentage_once" && (
        <label>
          Percentage rate % (required, e.g. 5.00)
          <input
            type="text"
            inputMode="decimal"
            required
            value={percentageText}
            onChange={(e) => setPercentageText(e.target.value)}
          />
        </label>
      )}
      {(formulaKind === "daily_flat" || formulaKind === "fixed_plus_daily_flat") && (
        <>
          <label>
            Daily amount USD (required)
            <input
              type="text"
              inputMode="decimal"
              required
              value={dailyDollars}
              onChange={(e) => setDailyDollars(e.target.value)}
            />
          </label>
          <label>
            Max accrual days (1–365; required if no cap)
            <input
              type="number"
              min={1}
              max={365}
              value={maxAccrualDays}
              onChange={(e) => setMaxAccrualDays(e.target.value)}
            />
          </label>
        </>
      )}
      <label>
        Per-period cap USD (optional; required for daily formulas without max days)
        <input
          type="text"
          inputMode="decimal"
          value={capDollars}
          onChange={(e) => setCapDollars(e.target.value)}
        />
      </label>
      <label>
        Per-period minimum USD (optional)
        <input
          type="text"
          inputMode="decimal"
          value={minDollars}
          onChange={(e) => setMinDollars(e.target.value)}
        />
      </label>
      <label>
        Minimum unpaid threshold USD (optional, default 0.00)
        <input
          type="text"
          inputMode="decimal"
          value={thresholdDollars}
          onChange={(e) => setThresholdDollars(e.target.value)}
        />
      </label>
      <label>
        Rounding mode (required)
        <select
          value={roundingMode}
          onChange={(e) => setRoundingMode(e.target.value as RoundingMode)}
        >
          <option value="half_up">Half-up</option>
          <option value="floor">Floor (round down)</option>
        </select>
      </label>
      <label>
        <input
          type="checkbox"
          checked={appliesToProrated}
          onChange={(e) => setAppliesToProrated(e.target.checked)}
        />{" "}
        Applies to prorated rent periods
      </label>
      <label>
        Internal notes (optional, operator-only)
        <input
          type="text"
          maxLength={1000}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
        />
      </label>
      <label>
        <input
          type="checkbox"
          checked={confirmed}
          onChange={(e) => setConfirmed(e.target.checked)}
        />{" "}
        I confirm this policy matches the signed lease terms (required)
      </label>
      <div className="form-actions">
        <button type="submit" disabled={recovery.status === "submitting"}>
          {recovery.status === "submitting" ? "Saving policy…" : "Save late-fee policy"}
        </button>
        {recovery.status === "outcome_unknown" && (
          <button type="button" onClick={() => void recovery.checkOutcome()}>
            Check committed outcome
          </button>
        )}
        <button type="button" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}

function VoidPolicyControl({
  leaseId,
  policy,
  expectedRevision,
  onCommitted,
}: {
  leaseId: string;
  policy: Policy;
  expectedRevision: number;
  onCommitted: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const recovery = useOpsRecoveryCommand(
    leaseId,
    "finance.late_fee_policy.void",
    `Void policy version ${policy.versionNumber}`,
    () => {
      setOpen(false);
      onCommitted();
    },
  );

  if (!open) {
    return (
      <button type="button" onClick={() => setOpen(true)}>
        Void unused policy
      </button>
    );
  }
  async function handleVoid(event: React.FormEvent) {
    event.preventDefault();
    recovery.setErrorMessage(null);
    if (!confirmed || !reason.trim()) {
      recovery.setErrorMessage("Provide a reason and confirm before voiding.");
      return;
    }
    const result = await recovery.execute({
      expectedRevision,
      recoveryPayload: {
        expectedRevision,
        policyVersionId: policy.id,
        confirmed: true,
        reason: reason.trim(),
      },
      dispatch: (idempotencyKey) =>
        api.POST("/api/leases/{lease_id}/late-fee-policies/{policy_version_id}/void", {
          params: { path: { lease_id: leaseId, policy_version_id: policy.id } },
          body: { expectedRevision, idempotencyKey, confirmed: true, reason: reason.trim() },
        }),
    });
    if (result.ok) {
      setOpen(false);
      onCommitted();
    }
  }
  return (
    <form onSubmit={(e) => void handleVoid(e)}>
      {recovery.errorMessage && <p role="alert">{recovery.errorMessage}</p>}
      <label>
        Void reason (required)
        <input
          type="text"
          required
          maxLength={1000}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
        />
      </label>
      <label>
        <input
          type="checkbox"
          checked={confirmed}
          onChange={(e) => setConfirmed(e.target.checked)}
        />{" "}
        Confirm voiding policy version {policy.versionNumber}
      </label>
      <div className="form-actions">
        <button type="submit" disabled={recovery.status === "submitting"}>
          {recovery.status === "submitting" ? "Voiding…" : "Confirm void policy"}
        </button>
        {recovery.status === "outcome_unknown" && (
          <button type="button" onClick={() => void recovery.checkOutcome()}>
            Check committed outcome
          </button>
        )}
        <button type="button" onClick={() => setOpen(false)}>
          Cancel
        </button>
      </div>
    </form>
  );
}

function PreviewPeriodRow({
  leaseId,
  preview,
  currentRevision,
  item,
  replacesAssessmentId,
  onAssessed,
}: {
  leaseId: string;
  preview: PreviewResponse;
  currentRevision: number;
  item: PreviewItem;
  replacesAssessmentId: string | null;
  onAssessed: () => void;
}) {
  const [assessing, setAssessing] = useState(Boolean(replacesAssessmentId));
  const [confirmed, setConfirmed] = useState(false);
  const [ackProcessing, setAckProcessing] = useState(false);
  const [ackReason, setAckReason] = useState("");
  const [notes, setNotes] = useState("");
  const recovery = useOpsRecoveryCommand(
    leaseId,
    "finance.late_fee_assessment.create",
    `Assess late fee for due ${item.dueOn}`,
    () => {
      setAssessing(false);
      onAssessed();
    },
  );

  const revisionStale = preview.rentLedgerRevision !== currentRevision;
  const canAssess =
    item.eligibilityStatus === "eligible" &&
    !!item.previewFingerprint &&
    !preview.futureProjection &&
    !revisionStale;

  async function submitAssess(event: React.FormEvent) {
    event.preventDefault();
    recovery.setErrorMessage(null);
    if (revisionStale) {
      recovery.setErrorMessage(
        "The rent ledger changed after this preview. Refresh the preview before assessing.",
      );
      return;
    }
    if (!confirmed) {
      recovery.setErrorMessage("Explicit confirmation is required to assess a late fee.");
      return;
    }
    if (item.requiresProcessingAcknowledgment && (!ackProcessing || !ackReason.trim())) {
      recovery.setErrorMessage("Acknowledge processing payments with a reason before assessing.");
      return;
    }
    const payloadBody = {
      expectedRevision: preview.rentLedgerRevision,
      rentExpectationId: item.rentExpectationId,
      asOfDate: preview.asOfDate,
      previewFingerprint: item.previewFingerprint!,
      operatorConfirmed: true,
      acknowledgeProcessingPayments: ackProcessing,
      processingAcknowledgmentReason: ackProcessing ? ackReason.trim() : null,
      internalNotes: notes.trim() || null,
      replacesAssessmentId,
    };
    const result = await recovery.execute({
      expectedRevision: preview.rentLedgerRevision,
      recoveryPayload: payloadBody,
      dispatch: (idempotencyKey) =>
        api.POST("/api/leases/{lease_id}/late-fee-assessments", {
          params: { path: { lease_id: leaseId } },
          body: { ...payloadBody, idempotencyKey },
        }),
    });
    if (result.ok) {
      setAssessing(false);
      onAssessed();
    }
  }

  return (
    <details className="child-record-card" open={Boolean(replacesAssessmentId) || undefined}>
      <summary>
        Due {formatDate(item.dueOn)} ({formatDate(item.periodStartsOn)} –{" "}
        {formatDate(item.periodEndsOn)}) ·{" "}
        <strong>{ELIGIBILITY_LABELS[item.eligibilityStatus]}</strong> ·{" "}
        {usd(item.calculatedAmountMinor)}
      </summary>
      <p>
        Expected rent: {usd(item.expectedAmountMinor)} · Paid through grace:{" "}
        {usd(item.paidThroughGraceMinor)} · Paid after grace:{" "}
        {usd(item.paidAfterGraceThroughAsOfMinor)}
      </p>
      {item.scheduledPrepaidChecks.count > 0 && (
        <p role="note">
          Warning: {item.scheduledPrepaidChecks.count} scheduled prepaid check(s) totaling{" "}
          {usd(item.scheduledPrepaidChecks.totalMinor)} (not counted as received rent).
        </p>
      )}
      {item.processingPayments.count > 0 && (
        <p role="note">
          Warning: {item.processingPayments.count} processing payment(s) totaling{" "}
          {usd(item.processingPayments.totalMinor)}. Explicit acknowledgment required to assess.
        </p>
      )}
      <ol aria-label="Calculation steps">
        {item.calculationSteps.map((step, idx) => (
          <li key={`${step.stepCode}-${idx}`}>
            {step.label} — <code>{step.expression}</code>
          </li>
        ))}
      </ol>
      {canAssess && !assessing && (
        <button type="button" onClick={() => setAssessing(true)}>
          {replacesAssessmentId
            ? `Assess replacement late fee (${usd(item.calculatedAmountMinor)})`
            : `Assess late fee (${usd(item.calculatedAmountMinor)})`}
        </button>
      )}
      {assessing && (
        <form onSubmit={(e) => void submitAssess(e)} aria-label="Confirm late-fee assessment">
          <p>
            Confirm assessing <strong>{usd(item.calculatedAmountMinor)}</strong> for rent due{" "}
            {formatDate(item.dueOn)} under policy version {item.policyVersionNumber} (
            {item.ruleBasis})
            {replacesAssessmentId
              ? ` as a replacement for voided assessment ${replacesAssessmentId.slice(0, 8)}`
              : ""}
            .
          </p>
          {recovery.errorMessage && <p role="alert">{recovery.errorMessage}</p>}
          {item.requiresProcessingAcknowledgment && (
            <>
              <label>
                <input
                  type="checkbox"
                  checked={ackProcessing}
                  onChange={(e) => setAckProcessing(e.target.checked)}
                />{" "}
                Acknowledge processing payments exist for this period
              </label>
              <label>
                Acknowledgment reason (required)
                <input
                  type="text"
                  required
                  value={ackReason}
                  onChange={(e) => setAckReason(e.target.value)}
                />
              </label>
            </>
          )}
          <label>
            Internal notes (optional, operator-only)
            <input type="text" value={notes} onChange={(e) => setNotes(e.target.value)} />
          </label>
          <label>
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(e) => setConfirmed(e.target.checked)}
            />{" "}
            Confirm assessing this late fee (required)
          </label>
          <div className="form-actions">
            <button type="submit" disabled={recovery.status === "submitting" || revisionStale}>
              {recovery.status === "submitting" ? "Assessing…" : "Confirm assess late fee"}
            </button>
            {recovery.status === "outcome_unknown" && (
              <button type="button" onClick={() => void recovery.checkOutcome()}>
                Check committed outcome
              </button>
            )}
            <button type="button" onClick={() => setAssessing(false)}>
              Cancel
            </button>
          </div>
        </form>
      )}
    </details>
  );
}

function AssessedLateFeeRow({
  item,
  expectedRevision,
  onMutated,
  onStartReplacement,
}: {
  item: AssessmentSummary;
  expectedRevision: number;
  onMutated: () => void;
  onStartReplacement?: (target: {
    id: string;
    rentExpectationId: string;
    asOfDate: string;
  }) => void;
}) {
  const { scope } = useWorkspace();
  const [expanded, setExpanded] = useState(false);
  const [activeAction, setActiveAction] = useState<
    "pay" | "waive" | "void" | "void_and_replace" | null
  >(null);

  const detailQuery = useQuery({
    queryKey: scope.key("late-fee-assessment-detail", item.id),
    enabled: expanded,
    retry: false,
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/late-fee-assessments/{assessment_id}", {
          signal,
          params: { path: { assessment_id: item.id } },
        }),
      ),
  });

  const detail: AssessmentDetail | undefined = detailQuery.data;
  const rev = detail?.rentLedgerRevision ?? expectedRevision;

  return (
    <details
      className="child-record-card"
      open={expanded}
      onToggle={(event) => setExpanded(event.currentTarget.open)}
    >
      <summary>
        <span className="record-pill">{SETTLEMENT_LABELS[item.settlementStatus]}</span> · As of{" "}
        {formatDate(item.asOfDate)} · Assessed {usd(item.assessedAmountMinor)} · Remaining{" "}
        <strong>{usd(item.remainingBalanceMinor)}</strong>
        {item.sourceDriftWarning ? " · Source drift warning" : ""}
      </summary>
      {item.sourceDriftWarning && (
        <p role="alert">
          Rent receipts for this period changed after this fee was assessed. Review whether to keep,
          waive, or void and replace this assessment.
        </p>
      )}
      <dl>
        <div>
          <dt>Rule basis</dt>
          <dd>{item.ruleBasisSnapshot}</dd>
        </div>
        <div>
          <dt>Assessed / Waived / Paid / Remaining</dt>
          <dd>
            {usd(item.assessedAmountMinor)} / {usd(item.waivedAmountMinor)} /{" "}
            {usd(item.paidAmountMinor)} / {usd(item.remainingBalanceMinor)}
          </dd>
        </div>
        {item.replacesAssessmentId && (
          <div>
            <dt>Replaces voided assessment</dt>
            <dd>
              <Link to={`/money?record=late_fee_assessment&id=${item.replacesAssessmentId}`}>
                Previous assessment
              </Link>
            </dd>
          </div>
        )}
        {item.replacedByAssessmentId && (
          <div>
            <dt>Replaced by assessment</dt>
            <dd>
              <Link to={`/money?record=late_fee_assessment&id=${item.replacedByAssessmentId}`}>
                Replacement assessment
              </Link>
            </dd>
          </div>
        )}
      </dl>
      {detailQuery.isPending && <p role="status">Loading calculation breakdown…</p>}
      {detailQuery.error && <p role="alert">Detail unavailable: {detailQuery.error.message}</p>}
      {detail && (
        <>
          <ol aria-label="Frozen calculation steps">
            {detail.calculationSteps.map((step, idx) => (
              <li key={`${step.stepCode}-${idx}`}>
                {step.label} — <code>{step.expression}</code>
              </li>
            ))}
          </ol>
          {detail.waivers.length > 0 && (
            <div>
              <h5>Waivers</h5>
              <ul>
                {detail.waivers.map((w) => (
                  <li key={w.id}>
                    {formatDate(w.waivedOn)}: {usd(w.waivedAmountMinor)} — {w.reason}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {detail.allocations.length > 0 && (
            <div>
              <h5>Fee payments</h5>
              <ul>
                {detail.allocations.map((a) => (
                  <li key={a.allocationId}>
                    <Link to={`/money?record=late_fee_receipt&id=${a.receiptId}`}>
                      {formatDate(a.receivedOn)}: {usd(a.amountMinor)} ({a.receiptLifecycleStatus})
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
      {item.settlementStatus !== "voided" ? (
        <div className="form-actions">
          {item.remainingBalanceMinor > 0 && (
            <>
              <button type="button" onClick={() => setActiveAction("pay")}>
                Record late-fee payment
              </button>
              <button type="button" onClick={() => setActiveAction("waive")}>
                Waive
              </button>
            </>
          )}
          {item.paidAmountMinor === 0 && (
            <>
              <button type="button" onClick={() => setActiveAction("void")}>
                Void assessment
              </button>
              {onStartReplacement && (
                <button type="button" onClick={() => setActiveAction("void_and_replace")}>
                  Void and replace
                </button>
              )}
            </>
          )}
        </div>
      ) : (
        !item.replacedByAssessmentId &&
        onStartReplacement && (
          <div className="form-actions">
            <button
              type="button"
              onClick={() =>
                onStartReplacement({
                  id: item.id,
                  rentExpectationId: item.rentExpectationId,
                  asOfDate: item.asOfDate,
                })
              }
            >
              Replace voided assessment
            </button>
          </div>
        )
      )}
      {activeAction === "pay" && (
        <RecordStandaloneFeePaymentForm
          assessment={item}
          expectedRevision={rev}
          onCancel={() => setActiveAction(null)}
          onCommitted={() => {
            setActiveAction(null);
            onMutated();
          }}
        />
      )}
      {activeAction === "waive" && (
        <WaiveAssessmentForm
          assessment={item}
          expectedRevision={rev}
          onCancel={() => setActiveAction(null)}
          onCommitted={() => {
            setActiveAction(null);
            onMutated();
          }}
        />
      )}
      {(activeAction === "void" || activeAction === "void_and_replace") && (
        <VoidAssessmentForm
          assessment={item}
          expectedRevision={rev}
          replaceAfterVoid={activeAction === "void_and_replace"}
          onCancel={() => setActiveAction(null)}
          onCommitted={() => {
            const shouldReplace = activeAction === "void_and_replace";
            setActiveAction(null);
            onMutated();
            if (shouldReplace && onStartReplacement) {
              onStartReplacement({
                id: item.id,
                rentExpectationId: item.rentExpectationId,
                asOfDate: item.asOfDate,
              });
            }
          }}
        />
      )}
    </details>
  );
}

function RecordStandaloneFeePaymentForm({
  assessment,
  expectedRevision,
  replacesReceiptId = null,
  onCancel,
  onCommitted,
}: {
  assessment: AssessmentSummary;
  expectedRevision: number;
  replacesReceiptId?: string | null;
  onCancel: () => void;
  onCommitted: (receiptId?: string) => void;
}) {
  const [receivedOn, setReceivedOn] = useState(assessment.asOfDate);
  const [dollars, setDollars] = useState(cents(assessment.remainingBalanceMinor));
  const [method, setMethod] = useState<PaymentMethodKind>("check");
  const [maskedReference, setMaskedReference] = useState("");
  const [otherNote, setOtherNote] = useState("");
  const recovery = useOpsRecoveryCommand(
    assessment.leaseId,
    "finance.late_fee_receipt.create",
    "Record late-fee payment",
    () => onCommitted(),
  );

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    recovery.setErrorMessage(null);
    const minor = dollarCents(dollars);
    if (!minor || minor <= 0) {
      recovery.setErrorMessage("Enter a positive USD amount.");
      return;
    }
    if (method === "other" && !otherNote.trim()) {
      recovery.setErrorMessage("Other payment method note is required.");
      return;
    }
    const payloadBody = {
      expectedRevision,
      receivedOn,
      amountMinor: minor,
      currencyCode: "USD" as const,
      allocations: [{ assessmentId: assessment.id, amountMinor: minor }],
      paymentMethodKind: method,
      paymentMethodLabel: null,
      maskedReference: maskedReference.trim() || null,
      otherPaymentMethodNote: method === "other" ? otherNote.trim() : null,
      receivedByPartyId: null,
      replacesReceiptId,
      notes: null,
    };
    const result = await recovery.execute({
      expectedRevision,
      recoveryPayload: payloadBody,
      dispatch: (idempotencyKey) =>
        api.POST("/api/leases/{lease_id}/late-fee-receipts", {
          params: { path: { lease_id: assessment.leaseId } },
          body: { ...payloadBody, idempotencyKey },
        }),
    });
    if (result.ok) onCommitted(result.data?.id);
  }

  return (
    <form onSubmit={(e) => void submit(e)} aria-label="Record late-fee payment">
      <h5>
        {replacesReceiptId ? "Record replacement late-fee payment" : "Record late-fee payment"}
      </h5>
      {recovery.errorMessage && <p role="alert">{recovery.errorMessage}</p>}
      <label>
        Received date (required)
        <input
          type="date"
          required
          value={receivedOn}
          onChange={(e) => setReceivedOn(e.target.value)}
        />
      </label>
      <label>
        Amount USD (required)
        <input
          type="text"
          inputMode="decimal"
          required
          value={dollars}
          onChange={(e) => setDollars(e.target.value)}
        />
      </label>
      <label>
        Payment method (required)
        <select value={method} onChange={(e) => setMethod(e.target.value as PaymentMethodKind)}>
          {PAYMENT_METHODS.map((item) => (
            <option key={item.value} value={item.value}>
              {item.label}
            </option>
          ))}
        </select>
      </label>
      <label>
        Masked reference (optional, e.g. Check •••• 9182)
        <input
          type="text"
          maxLength={80}
          value={maskedReference}
          onChange={(e) => setMaskedReference(e.target.value)}
        />
      </label>
      {method === "other" && (
        <label>
          Other payment method note (required)
          <input
            type="text"
            required
            maxLength={200}
            value={otherNote}
            onChange={(e) => setOtherNote(e.target.value)}
          />
        </label>
      )}
      <div className="form-actions">
        <button type="submit" disabled={recovery.status === "submitting"}>
          {recovery.status === "submitting" ? "Recording…" : "Save late-fee payment"}
        </button>
        {recovery.status === "outcome_unknown" && (
          <button type="button" onClick={() => void recovery.checkOutcome()}>
            Check committed outcome
          </button>
        )}
        <button type="button" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}

function WaiveAssessmentForm({
  assessment,
  expectedRevision,
  onCancel,
  onCommitted,
}: {
  assessment: AssessmentSummary;
  expectedRevision: number;
  onCancel: () => void;
  onCommitted: () => void;
}) {
  const [dollars, setDollars] = useState(cents(assessment.remainingBalanceMinor));
  const [waivedOn, setWaivedOn] = useState(assessment.asOfDate);
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const recovery = useOpsRecoveryCommand(
    assessment.leaseId,
    "finance.late_fee_assessment.waive",
    "Waive late fee",
    onCommitted,
  );

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    recovery.setErrorMessage(null);
    const minor = dollarCents(dollars);
    if (!minor || minor <= 0 || !confirmed || !reason.trim()) {
      recovery.setErrorMessage("Enter a valid amount, reason, and confirmation.");
      return;
    }
    const result = await recovery.execute({
      expectedRevision,
      recoveryPayload: {
        expectedRevision,
        assessmentId: assessment.id,
        waivedAmountMinor: minor,
        waivedOn,
        reason: reason.trim(),
        confirmed: true,
        internalNotes: null,
      },
      dispatch: (idempotencyKey) =>
        api.POST("/api/late-fee-assessments/{assessment_id}/waive", {
          params: { path: { assessment_id: assessment.id } },
          body: {
            expectedRevision,
            idempotencyKey,
            waivedAmountMinor: minor,
            waivedOn,
            reason: reason.trim(),
            confirmed: true,
            internalNotes: null,
          },
        }),
    });
    if (result.ok) onCommitted();
  }

  return (
    <form onSubmit={(e) => void submit(e)} aria-label="Waive late fee">
      <h5>Waive late fee (partial or full)</h5>
      {recovery.errorMessage && <p role="alert">{recovery.errorMessage}</p>}
      <label>
        Waive amount USD (required)
        <input
          type="text"
          inputMode="decimal"
          required
          value={dollars}
          onChange={(e) => setDollars(e.target.value)}
        />
      </label>
      <label>
        Waived date (required)
        <input
          type="date"
          required
          value={waivedOn}
          onChange={(e) => setWaivedOn(e.target.value)}
        />
      </label>
      <label>
        Reason (required; visible to tenant and owner)
        <input
          type="text"
          required
          maxLength={1000}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
        />
      </label>
      <label>
        <input
          type="checkbox"
          checked={confirmed}
          onChange={(e) => setConfirmed(e.target.checked)}
        />{" "}
        Confirm waiver
      </label>
      <div className="form-actions">
        <button type="submit" disabled={recovery.status === "submitting"}>
          {recovery.status === "submitting" ? "Waiving…" : "Confirm waive"}
        </button>
        {recovery.status === "outcome_unknown" && (
          <button type="button" onClick={() => void recovery.checkOutcome()}>
            Check committed outcome
          </button>
        )}
        <button type="button" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}

function VoidAssessmentForm({
  assessment,
  expectedRevision,
  replaceAfterVoid = false,
  onCancel,
  onCommitted,
}: {
  assessment: AssessmentSummary;
  expectedRevision: number;
  replaceAfterVoid?: boolean;
  onCancel: () => void;
  onCommitted: () => void;
}) {
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const recovery = useOpsRecoveryCommand(
    assessment.leaseId,
    "finance.late_fee_assessment.void",
    replaceAfterVoid ? "Void and replace late-fee assessment" : "Void late-fee assessment",
    onCommitted,
  );

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    recovery.setErrorMessage(null);
    if (!confirmed || !reason.trim()) {
      recovery.setErrorMessage("Provide a reason and confirm before voiding.");
      return;
    }
    const result = await recovery.execute({
      expectedRevision,
      recoveryPayload: {
        expectedRevision,
        assessmentId: assessment.id,
        confirmed: true,
        reason: reason.trim(),
      },
      dispatch: (idempotencyKey) =>
        api.POST("/api/late-fee-assessments/{assessment_id}/void", {
          params: { path: { assessment_id: assessment.id } },
          body: { expectedRevision, idempotencyKey, confirmed: true, reason: reason.trim() },
        }),
    });
    if (result.ok) onCommitted();
  }

  return (
    <form onSubmit={(e) => void submit(e)} aria-label="Void late-fee assessment">
      <h5>
        {replaceAfterVoid ? "Void and replace late-fee assessment" : "Void late-fee assessment"}
      </h5>
      {replaceAfterVoid && (
        <p>
          Voiding this assessment will immediately open a fresh preview linked as its replacement.
        </p>
      )}
      {recovery.errorMessage && <p role="alert">{recovery.errorMessage}</p>}
      <label>
        Void reason (required)
        <input
          type="text"
          required
          maxLength={1000}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
        />
      </label>
      <label>
        <input
          type="checkbox"
          checked={confirmed}
          onChange={(e) => setConfirmed(e.target.checked)}
        />{" "}
        Confirm voiding {usd(assessment.assessedAmountMinor)} assessment
      </label>
      <div className="form-actions">
        <button type="submit" disabled={recovery.status === "submitting"}>
          {recovery.status === "submitting"
            ? "Voiding…"
            : replaceAfterVoid
              ? "Confirm void and preview replacement"
              : "Confirm void"}
        </button>
        {recovery.status === "outcome_unknown" && (
          <button type="button" onClick={() => void recovery.checkOutcome()}>
            Check committed outcome
          </button>
        )}
        <button type="button" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}

export function CombinedReceiptForm({
  leaseId,
  expectedRevision,
  initialReceivedOn = "",
  initialExpectationId = "",
  initialMethod = "check",
  initialMaskedReference = "",
  initialOtherNote = "",
  onCancel,
  onCommitted,
}: {
  leaseId: string;
  expectedRevision: number;
  initialReceivedOn?: string;
  initialExpectationId?: string;
  initialMethod?: PaymentMethodKind;
  initialMaskedReference?: string;
  initialOtherNote?: string;
  onCancel: () => void;
  onCommitted: () => void;
}) {
  const { scope } = useWorkspace();
  const [receivedOn, setReceivedOn] = useState(initialReceivedOn);
  const [selectedExpId, setSelectedExpId] = useState(initialExpectationId);
  const [rentDollars, setRentDollars] = useState("");
  const [selectedFeeId, setSelectedFeeId] = useState("");
  const [feeDollars, setFeeDollars] = useState("");
  const [method, setMethod] = useState<PaymentMethodKind>(initialMethod);
  const [maskedReference, setMaskedReference] = useState(initialMaskedReference);
  const [otherNote, setOtherNote] = useState(initialOtherNote);
  const [duplicateMatchSig, setDuplicateMatchSig] = useState<string | null>(null);
  const [duplicateConfirmed, setDuplicateConfirmed] = useState(false);
  const [duplicateReason, setDuplicateReason] = useState("");
  const recovery = useOpsRecoveryCommand(
    leaseId,
    "finance.combined_receipt.create",
    "Record combined rent + late-fee payment",
    onCommitted,
  );

  function clearDuplicateState() {
    if (duplicateMatchSig !== null) {
      setDuplicateMatchSig(null);
      setDuplicateConfirmed(false);
      setDuplicateReason("");
    }
  }

  const expPages = useInfiniteQuery({
    queryKey: scope.key("combined-receipt-open-rent", leaseId),
    initialPageParam: null as string | null,
    retry: false,
    queryFn: async ({ pageParam, signal }) =>
      readResult(
        await api.GET("/api/rent-expectations", {
          signal,
          params: { query: { leaseId, pageSize: 50, cursor: pageParam ?? undefined } },
        }),
      ),
    getNextPageParam: (page) => page.nextCursor ?? undefined,
  });

  const feePages = useInfiniteQuery({
    queryKey: scope.key("combined-receipt-open-fees", leaseId),
    initialPageParam: null as string | null,
    retry: false,
    queryFn: async ({ pageParam, signal }) =>
      readResult(
        await api.GET("/api/leases/{lease_id}/late-fee-assessments", {
          signal,
          params: {
            path: { lease_id: leaseId },
            query: { includeVoided: false, pageSize: 50, cursor: pageParam ?? undefined },
          },
        }),
      ),
    getNextPageParam: (page) => page.nextCursor ?? undefined,
  });

  const openRent = (expPages.data?.pages ?? [])
    .flatMap((page) => page.items)
    .filter((e) => !e.voidedAt && e.outstandingAmountMinor > 0);
  const unpaidAssessments = (feePages.data?.pages ?? [])
    .flatMap((page) => page.items)
    .filter((item) => item.remainingBalanceMinor > 0 && item.settlementStatus !== "voided");

  const effectiveFeeId = selectedFeeId || (unpaidAssessments[0]?.id ?? "");
  const effectiveFee = unpaidAssessments.find((x) => x.id === effectiveFeeId);
  const effectiveReceivedOn = receivedOn || (effectiveFee?.asOfDate ?? "");
  const effectiveFeeDollars =
    feeDollars !== "" ? feeDollars : effectiveFee ? cents(effectiveFee.remainingBalanceMinor) : "";
  const effectiveExp = openRent.find((x) => x.id === selectedExpId);
  const effectiveRentDollars =
    rentDollars !== ""
      ? rentDollars
      : effectiveExp
        ? cents(effectiveExp.outstandingAmountMinor)
        : "";

  const rentMinor = dollarCents(effectiveRentDollars) ?? 0;
  const feeMinor = dollarCents(effectiveFeeDollars) ?? 0;
  const duplicateSignature = `${effectiveReceivedOn}|${selectedExpId}|${rentMinor}`;
  const needsDuplicateConfirm =
    duplicateMatchSig !== null && duplicateMatchSig === duplicateSignature;
  const inputsLocked = recovery.status === "submitting" || recovery.status === "outcome_unknown";

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    recovery.setErrorMessage(null);
    if (!selectedExpId || !effectiveFeeId || rentMinor <= 0 || feeMinor <= 0) {
      recovery.setErrorMessage(
        "Select an open rent period, an unpaid late fee, and positive USD amounts.",
      );
      return;
    }
    if (method === "other" && !otherNote.trim()) {
      recovery.setErrorMessage("Other payment method note is required.");
      return;
    }
    if (needsDuplicateConfirm && (!duplicateConfirmed || !duplicateReason.trim())) {
      recovery.setErrorMessage(
        "Confirm recording a separate rent payment and provide a duplicate confirmation reason.",
      );
      return;
    }
    const submittedSig = duplicateSignature;
    const payloadBody = {
      expectedRevision,
      receivedOn: effectiveReceivedOn,
      currencyCode: "USD" as const,
      rentAllocations: [{ expectationId: selectedExpId, amountMinor: rentMinor }],
      lateFeeAllocations: [{ assessmentId: effectiveFeeId, amountMinor: feeMinor }],
      paymentMethodKind: method,
      paymentMethodLabel: null,
      maskedReference: maskedReference.trim() || null,
      otherPaymentMethodNote: method === "other" ? otherNote.trim() : null,
      receivedByPartyId: null,
      notes: null,
      duplicateConfirmed: needsDuplicateConfirm && duplicateConfirmed,
      duplicateReason: needsDuplicateConfirm && duplicateConfirmed ? duplicateReason.trim() : null,
    };
    const result = await recovery.execute({
      expectedRevision,
      recoveryPayload: payloadBody,
      dispatch: (idempotencyKey) =>
        api.POST("/api/leases/{lease_id}/combined-receipts", {
          params: { path: { lease_id: leaseId } },
          body: { ...payloadBody, idempotencyKey },
        }),
    });
    if (!result.ok) {
      if (isDuplicateReceiptError(result.error)) {
        setDuplicateMatchSig(submittedSig);
      }
      return;
    }
    onCommitted();
  }

  return (
    <form
      className="child-record-card"
      aria-label="Record combined rent and late-fee payment"
      onSubmit={(e) => void submit(e)}
    >
      <h5>Record combined rent + assessed late-fee payment</h5>
      <p>
        Creates separate rent and late-fee receipts atomically linked by one batch ID. Rent
        subtotal: <strong>{usd(rentMinor)}</strong> · Late fee subtotal:{" "}
        <strong>{usd(feeMinor)}</strong> · Total received:{" "}
        <strong>{usd(rentMinor + feeMinor)}</strong>
      </p>
      {recovery.errorMessage && <p role="alert">{recovery.errorMessage}</p>}
      <label>
        Received date (required)
        <input
          type="date"
          required
          disabled={inputsLocked}
          value={effectiveReceivedOn}
          onChange={(e) => {
            setReceivedOn(e.target.value);
            clearDuplicateState();
          }}
        />
      </label>
      <label>
        Rent period (required)
        <select
          required
          disabled={inputsLocked}
          value={selectedExpId}
          onChange={(e) => {
            setSelectedExpId(e.target.value);
            const found = openRent.find((x) => x.id === e.target.value);
            if (found) setRentDollars(cents(found.outstandingAmountMinor));
            clearDuplicateState();
          }}
        >
          <option value="">Select open rent period…</option>
          {openRent.map((exp) => (
            <option key={exp.id} value={exp.id}>
              Due {formatDate(exp.dueOn)} — {usd(exp.outstandingAmountMinor)} open
            </option>
          ))}
        </select>
      </label>
      {expPages.hasNextPage && (
        <button
          type="button"
          disabled={inputsLocked || expPages.isFetchingNextPage}
          onClick={() => void expPages.fetchNextPage()}
        >
          {expPages.isFetchingNextPage ? "Loading rent periods…" : "Load more rent periods"}
        </button>
      )}
      <label>
        Rent subtotal USD (required)
        <input
          type="text"
          inputMode="decimal"
          required
          disabled={inputsLocked}
          value={effectiveRentDollars}
          onChange={(e) => {
            setRentDollars(e.target.value);
            clearDuplicateState();
          }}
        />
      </label>
      <label>
        Assessed late fee (required)
        <select
          required
          value={effectiveFeeId}
          onChange={(e) => {
            setSelectedFeeId(e.target.value);
            const found = unpaidAssessments.find((x) => x.id === e.target.value);
            if (found) setFeeDollars(cents(found.remainingBalanceMinor));
          }}
        >
          <option value="">Select unpaid late fee…</option>
          {unpaidAssessments.map((fee) => (
            <option key={fee.id} value={fee.id}>
              As of {formatDate(fee.asOfDate)} — {usd(fee.remainingBalanceMinor)} open
            </option>
          ))}
        </select>
      </label>
      {feePages.hasNextPage && (
        <button
          type="button"
          disabled={feePages.isFetchingNextPage}
          onClick={() => void feePages.fetchNextPage()}
        >
          {feePages.isFetchingNextPage ? "Loading late fees…" : "Load more late fees"}
        </button>
      )}
      <label>
        Late fee subtotal USD (required)
        <input
          type="text"
          inputMode="decimal"
          required
          value={effectiveFeeDollars}
          onChange={(e) => setFeeDollars(e.target.value)}
        />
      </label>
      <label>
        Payment method (required)
        <select value={method} onChange={(e) => setMethod(e.target.value as PaymentMethodKind)}>
          {PAYMENT_METHODS.map((item) => (
            <option key={item.value} value={item.value}>
              {item.label}
            </option>
          ))}
        </select>
      </label>
      {method === "other" && (
        <label>
          Other payment method note (required)
          <input
            type="text"
            required
            maxLength={200}
            value={otherNote}
            onChange={(e) => setOtherNote(e.target.value)}
          />
        </label>
      )}
      <label>
        Masked reference (optional, e.g. Check •••• 8888)
        <input
          type="text"
          maxLength={80}
          value={maskedReference}
          onChange={(e) => setMaskedReference(e.target.value)}
        />
      </label>
      {needsDuplicateConfirm && (
        <div className="record-detail-panel" role="region" aria-label="Duplicate payment review">
          <p>
            A matching active rent receipt already exists for this date and amount. Confirm only if
            this is a separate payment.
          </p>
          <label>
            <input
              type="checkbox"
              checked={duplicateConfirmed}
              onChange={(e) => setDuplicateConfirmed(e.target.checked)}
            />{" "}
            Confirm recording a separate rent payment
          </label>
          <label>
            Duplicate confirmation reason (required)
            <input
              type="text"
              required
              maxLength={500}
              value={duplicateReason}
              onChange={(e) => setDuplicateReason(e.target.value)}
            />
          </label>
        </div>
      )}
      <div className="form-actions">
        <button
          type="submit"
          disabled={
            recovery.status === "submitting" ||
            recovery.status === "outcome_unknown" ||
            recovery.recoveryCheckFailed
          }
        >
          {recovery.status === "submitting"
            ? "Recording combined payment…"
            : "Save combined payment"}
        </button>
        {recovery.recoveryCheckFailed && (
          <button type="button" onClick={recovery.retryRecoveryCheck}>
            Retry recovery check
          </button>
        )}
        {recovery.status === "outcome_unknown" && (
          <button type="button" onClick={() => void recovery.checkOutcome()}>
            Check committed outcome
          </button>
        )}
        <button type="button" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}

export function IncludeAssessedLateFeesSection({
  leaseId,
  expectedRevision,
  initialReceivedOn,
  initialExpectationId,
  onCommitted,
}: {
  leaseId: string;
  expectedRevision: number;
  initialReceivedOn?: string;
  initialExpectationId?: string;
  onCommitted: () => void;
}) {
  const [includeFees, setIncludeFees] = useState(false);

  return (
    <section className="record-detail-panel" aria-label="Include assessed late fees">
      <label>
        <input
          type="checkbox"
          checked={includeFees}
          onChange={(e) => setIncludeFees(e.target.checked)}
        />{" "}
        Include assessed late fees with this payment (atomic rent + late-fee split)
      </label>
      {includeFees && (
        <CombinedReceiptForm
          leaseId={leaseId}
          expectedRevision={expectedRevision}
          initialReceivedOn={initialReceivedOn}
          initialExpectationId={initialExpectationId}
          onCancel={() => setIncludeFees(false)}
          onCommitted={onCommitted}
        />
      )}
    </section>
  );
}

export function LateFeeReceiptActions({
  receipt,
  onMutated,
}: {
  receipt: Record<string, unknown>;
  onMutated: () => void;
}) {
  const { scope } = useWorkspace();
  const navigate = useNavigate();
  const receiptId = scalar(receipt.id, "");
  const leaseId = scalar(receipt.leaseId, "");
  const voidedAt = receipt.voidedAt ? scalar(receipt.voidedAt, "") : null;
  const replacesReceiptId = receipt.replacesReceiptId
    ? scalar(receipt.replacesReceiptId, "")
    : null;
  const replacedByReceiptId = receipt.replacedByReceiptId
    ? scalar(receipt.replacedByReceiptId, "")
    : null;
  const revision = typeof receipt.rentLedgerRevision === "number" ? receipt.rentLedgerRevision : 0;

  const [mode, setMode] = useState<"void" | "replace" | null>(null);
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [selectedAssessmentId, setSelectedAssessmentId] = useState("");

  const voidRecovery = useOpsRecoveryCommand(
    leaseId,
    "finance.late_fee_receipt.void",
    "Void late-fee payment",
    () => {
      setMode(null);
      onMutated();
    },
  );

  const openAssessments = useInfiniteQuery({
    queryKey: scope.key("replace-fee-receipt-targets", leaseId),
    enabled: mode === "replace",
    initialPageParam: null as string | null,
    retry: false,
    queryFn: async ({ pageParam, signal }) =>
      readResult(
        await api.GET("/api/leases/{lease_id}/late-fee-assessments", {
          signal,
          params: {
            path: { lease_id: leaseId },
            query: { includeVoided: false, pageSize: 50, cursor: pageParam ?? undefined },
          },
        }),
      ),
    getNextPageParam: (page) => page.nextCursor ?? undefined,
  });

  const unpaid = (openAssessments.data?.pages ?? [])
    .flatMap((page) => page.items)
    .filter((item) => item.remainingBalanceMinor > 0 && item.settlementStatus !== "voided");

  const chosenAssessment =
    unpaid.find((item) => item.id === selectedAssessmentId) ?? unpaid[0] ?? null;

  async function submitVoid(event: React.FormEvent) {
    event.preventDefault();
    voidRecovery.setErrorMessage(null);
    if (!confirmed || !reason.trim()) {
      voidRecovery.setErrorMessage("Provide a reason and confirm before voiding this receipt.");
      return;
    }
    const result = await voidRecovery.execute({
      expectedRevision: revision,
      recoveryPayload: {
        expectedRevision: revision,
        receiptId,
        confirmed: true,
        reason: reason.trim(),
      },
      dispatch: (idempotencyKey) =>
        api.POST("/api/late-fee-receipts/{receipt_id}/void", {
          params: { path: { receipt_id: receiptId } },
          body: {
            expectedRevision: revision,
            idempotencyKey,
            confirmed: true,
            reason: reason.trim(),
          },
        }),
    });
    if (result.ok) {
      setMode(null);
      onMutated();
    }
  }

  return (
    <section aria-label="Late-fee payment actions" className="record-detail-panel">
      {(replacesReceiptId || replacedByReceiptId) && (
        <nav aria-label="Correction history">
          {replacesReceiptId && (
            <Link to={`/money?record=late_fee_receipt&id=${replacesReceiptId}`}>
              Previous late-fee payment
            </Link>
          )}
          {replacedByReceiptId && (
            <Link to={`/money?record=late_fee_receipt&id=${replacedByReceiptId}`}>
              Replacement late-fee payment
            </Link>
          )}
        </nav>
      )}
      {!voidedAt && mode !== "void" && (
        <button type="button" onClick={() => setMode("void")}>
          Void late-fee payment
        </button>
      )}
      {voidedAt && !replacedByReceiptId && mode !== "replace" && (
        <button type="button" onClick={() => setMode("replace")}>
          Record replacement late-fee payment
        </button>
      )}
      {mode === "void" && (
        <form onSubmit={(e) => void submitVoid(e)} aria-label="Void late-fee payment">
          <h4>Void late-fee payment</h4>
          {voidRecovery.errorMessage && <p role="alert">{voidRecovery.errorMessage}</p>}
          <label>
            Void reason (required)
            <input
              type="text"
              required
              maxLength={1000}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          </label>
          <label>
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(e) => setConfirmed(e.target.checked)}
            />{" "}
            Confirm voiding this late-fee payment
          </label>
          <div className="form-actions">
            <button type="submit" disabled={voidRecovery.status === "submitting"}>
              {voidRecovery.status === "submitting" ? "Voiding…" : "Confirm void payment"}
            </button>
            {voidRecovery.status === "outcome_unknown" && (
              <button type="button" onClick={() => void voidRecovery.checkOutcome()}>
                Check committed outcome
              </button>
            )}
            <button type="button" onClick={() => setMode(null)}>
              Cancel
            </button>
          </div>
        </form>
      )}
      {mode === "replace" && (
        <div className="child-record-card">
          {openAssessments.isPending && <p role="status">Loading unpaid late fees…</p>}
          {openAssessments.data && unpaid.length === 0 && (
            <p>No unpaid late-fee assessments remain on this lease.</p>
          )}
          {unpaid.length > 0 && (
            <>
              <label>
                Target late-fee assessment
                <select
                  value={chosenAssessment?.id ?? ""}
                  onChange={(e) => setSelectedAssessmentId(e.target.value)}
                >
                  {unpaid.map((fee) => (
                    <option key={fee.id} value={fee.id}>
                      As of {formatDate(fee.asOfDate)} — {usd(fee.remainingBalanceMinor)} open
                    </option>
                  ))}
                </select>
              </label>
              {openAssessments.hasNextPage && (
                <button
                  type="button"
                  disabled={openAssessments.isFetchingNextPage}
                  onClick={() => void openAssessments.fetchNextPage()}
                >
                  {openAssessments.isFetchingNextPage ? "Loading…" : "Load more late fees"}
                </button>
              )}
              {chosenAssessment && (
                <RecordStandaloneFeePaymentForm
                  assessment={chosenAssessment}
                  expectedRevision={revision}
                  replacesReceiptId={receiptId}
                  onCancel={() => setMode(null)}
                  onCommitted={(newId) => {
                    setMode(null);
                    onMutated();
                    if (newId) void navigate(`/money?record=late_fee_receipt&id=${newId}`);
                  }}
                />
              )}
            </>
          )}
        </div>
      )}
    </section>
  );
}

export function MoneyLateFeesQueue() {
  const { scope } = useWorkspace();
  const queryClient = useQueryClient();
  const [params, setParams] = useSearchParams();
  const propertyId = params.get("propertyId") ?? undefined;
  const leaseId = params.get("leaseId") ?? undefined;
  const settlementStatus = (params.get("settlementStatus") ?? undefined) as
    AssessmentSummary["settlementStatus"] | undefined;
  const includeVoided = params.get("includeVoided") === "true";
  const cursor = params.get("cursor") ?? undefined;

  const queue = useQuery({
    queryKey: scope.key(
      "portfolio-late-fee-assessments",
      propertyId,
      leaseId,
      settlementStatus,
      includeVoided,
      cursor,
    ),
    retry: false,
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/late-fee-assessments", {
          signal,
          params: {
            query: {
              propertyId,
              leaseId,
              settlementStatus,
              includeVoided,
              cursor,
              pageSize: 50,
            },
          },
        }),
      ),
  });

  function updateFilter(key: string, value: string | null) {
    const next = new URLSearchParams(params);
    next.delete("cursor");
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true, preventScrollReset: true });
  }

  return (
    <section aria-label="Late fees queue" className="money-directory">
      <h3>Assessed late fees</h3>
      <div className="money-directory-filters">
        <label>
          Settlement status
          <select
            value={settlementStatus ?? ""}
            onChange={(e) => updateFilter("settlementStatus", e.target.value || null)}
          >
            <option value="">All active statuses</option>
            <option value="unpaid">Unpaid</option>
            <option value="partially_paid">Partially paid</option>
            <option value="paid">Paid</option>
            <option value="waived">Waived</option>
            <option value="voided">Voided</option>
          </select>
        </label>
        <label>
          <input
            type="checkbox"
            checked={includeVoided}
            onChange={(e) => updateFilter("includeVoided", e.target.checked ? "true" : null)}
          />{" "}
          Include voided history
        </label>
      </div>
      {queue.isPending && <p role="status">Loading assessed late fees…</p>}
      {queue.error && (
        <div role="alert">
          <p>Assessed late fees are unavailable: {queue.error.message}</p>
          <button
            type="button"
            onClick={() => {
              if (cursor) {
                const next = new URLSearchParams(params);
                next.delete("cursor");
                setParams(next, { replace: true });
              } else {
                void queue.refetch();
              }
            }}
          >
            {cursor ? "Restart with these filters" : "Retry"}
          </button>
        </div>
      )}
      {queue.data && queue.data.items.length === 0 && (
        <p>No assessed late fees match these filters.</p>
      )}
      {queue.data && queue.data.items.length > 0 && (
        <>
          <p className="record-detail-note">
            Click anywhere on an item’s summary bar to expand or collapse its details.
          </p>
          {queue.data.items.map((item) => (
            <div key={item.id}>
              <p>
                <Link to={`/leases/${item.leaseId}/details`}>Open Lease →</Link>
              </p>
              <AssessedLateFeeRow
                item={item}
                expectedRevision={0}
                onMutated={() => {
                  void queryClient.invalidateQueries({
                    queryKey: scope.key("portfolio-late-fee-assessments"),
                  });
                }}
              />
            </div>
          ))}
          {queue.data.nextCursor && (
            <button
              type="button"
              onClick={() => {
                const next = new URLSearchParams(params);
                next.set("cursor", queue.data.nextCursor!);
                setParams(next);
              }}
            >
              Next page
            </button>
          )}
        </>
      )}
    </section>
  );
}
