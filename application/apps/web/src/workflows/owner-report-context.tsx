import { DynamicFilterForm } from "../shared/dynamic-filter-form";
import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "@epm/contracts";
import { scalar } from "@epm/contracts/workflows";
import { useWorkspace } from "../app/workspace-gate";
import { readResult } from "./reads";
import { MoneyFacts } from "./money-presentation";
import { ReceiptAllocationContext, receiptBalance } from "./rent-context";
import { formatDate } from "../shared/presentation";

export function ownerVerificationProblem(
  values: Record<string, unknown>,
  report: Record<string, unknown>,
  mode?: string,
) {
  if (report.status !== "pending") return "Only a pending report can be verified.";
  if (Number(report.evidenceCount) < 1)
    return "Attach available evidence before verification; a claim alone is not income.";
  if (
    mode === "create" &&
    receiptBalance({ ...values, amountMinor: report.amountMinor }).remaining !== 0n
  )
    return "Allocate exactly the reported USD amount before creating its receipt.";
  return undefined;
}

export function OwnerReportContext({
  values,
  report,
  locked,
  onChange,
  mode,
  editableOwner,
}: {
  values: Record<string, unknown>;
  report: Record<string, unknown>;
  locked: boolean;
  onChange: (values: Record<string, unknown>) => void;
  mode?: string;
  editableOwner: boolean;
}) {
  const { scope } = useWorkspace();
  const leaseId = scalar(values.leaseId ?? report.leaseId, "");
  const context = useQuery({
    queryKey: scope.key("owner-report-property", leaseId),
    enabled: !!leaseId,
    queryFn: async ({ signal }) => {
      const lease = readResult(
        await api.GET("/api/leases/{lease_id}", {
          signal,
          params: { path: { lease_id: leaseId } },
        }),
      );
      const space = readResult(
        await api.GET("/api/spaces/{space_id}/status", {
          signal,
          params: { path: { space_id: lease.spaceId } },
        }),
      );
      return readResult(
        await api.GET("/api/properties/{property_id}", {
          signal,
          params: { path: { property_id: space.propertyId } },
        }),
      );
    },
  });
  const received = scalar(values.receivedOn ?? report.receivedOn, "");
  const ownerId = scalar(values.ownerPartyId ?? report.ownerPartyId, "");
  const party = useQuery({
    queryKey: scope.key("owner-report-selected-party", ownerId),
    enabled: !!ownerId,
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/parties/{party_id}", {
          signal,
          params: { path: { party_id: ownerId } },
        }),
      ),
  });
  const eligible =
    context.data?.ownerships.filter(
      (owner) =>
        owner.ownerKind === "client_owner" &&
        owner.startsOn <= received &&
        (!owner.endsOn || received < owner.endsOn),
    ) ?? [];
  return (
    <section aria-label="Owner report review">
      <p>
        This is one client Owner's claim, not income. Only its active Finance receipt counts. No
        ownership percentage, legal entitlement, statement or disbursement is inferred.
      </p>
      <p>
        The recorded time is saved automatically. Received on is the date the owner received the
        payment.
      </p>
      <p>
        Eligibility uses the payment date in the Property's time zone. Ended ownership and archived
        identity can be truthful historical context; Local operator uses ordinary Finance receipts,
        never a fabricated Owner Party.
      </p>
      {context.isPending && leaseId && <p role="status">Loading historical ownership context…</p>}
      {context.error && <p role="alert">Ownership context unavailable: {context.error.message}</p>}
      {context.data && (
        <>
          <p>
            {context.data.displayName} · {context.data.timeZone} · Current ownership context for
            payment on {received ? formatDate(received) : "the selected payment date"}
          </p>
          {eligible.map((owner) => (
            <p key={owner.id}>
              {owner.party?.displayName ?? "Owner name unavailable"} · {formatDate(owner.startsOn)}{" "}
              to {owner.endsOn ? formatDate(owner.endsOn) : "current"}
              {owner.party?.archivedAt && " · Archived identity — historical selection only"}{" "}
              {editableOwner && (
                <button
                  type="button"
                  disabled={locked}
                  onClick={() => onChange({ ...values, ownerPartyId: owner.partyId })}
                >
                  Use owner {owner.party?.displayName ?? owner.partyId}
                </button>
              )}
            </p>
          ))}
          <p>
            Ended relationships are not included in this current Property view. For historical
            reports use the retained Owner identity; the server checks its ownership on the payment
            date.
          </p>
        </>
      )}
      {party.data && (
        <p>
          Selected Owner: {party.data.displayName}
          {party.data.archivedAt
            ? " · Archived identity — historical selection only"
            : " · Active identity"}
          . This is identity state, not proof of date-effective ownership.
        </p>
      )}
      {party.error && <p role="alert">Selected Owner unavailable: {party.error.message}</p>}
      {Object.keys(report).length > 0 && (
        <MoneyFacts
          value={report}
          fields={[
            "ownerDisplayNameSnapshot",
            "currentOwnerState",
            "receivedOn",
            "reportedAtUtc",
            "amountMinor",
            "paymentMethodKind",
            "paymentMethodLabel",
            "maskedReference",
            "evidenceCount",
            "receiptLifecycleStatus",
            "financiallyEffective",
          ]}
          labels={{ reportedAtUtc: "Recorded" }}
        />
      )}
      {mode === "create" && (
        <ReceiptAllocationContext values={{ ...values, amountMinor: report.amountMinor }} />
      )}
      {!!report.replacesReportId && (
        <p>
          Replacement of{" "}
          <Link to={`/money?record=report&id=${scalar(report.replacesReportId)}`}>
            prior report
          </Link>
          . A verified predecessor's receipt must be voided first and its exact replacement linked.
        </p>
      )}
      {report.priorReceiptLifecycleStatus === "active" && (
        <p role="alert">
          The prior verified receipt is still active. Void it through Finance before verifying this
          replacement report.
        </p>
      )}
      {!!report.id && (
        <Link to={`/money?record=report&id=${scalar(report.id)}`}>
          Review report and retained evidence
        </Link>
      )}
    </section>
  );
}

export function OwnerReportFilters() {
  const [params, setParams] = useSearchParams();
  return (
    <DynamicFilterForm
      className="directory-filters"
      onSubmit={(event) => {
        event.preventDefault();
        const data = new FormData(event.currentTarget),
          next = new URLSearchParams(params);
        for (const key of [
          "status",
          "hasEvidence",
          "receiptLifecycleStatus",
          "receivedFrom",
          "receivedTo",
        ]) {
          const value = data.get(key);
          if (typeof value === "string" && value) next.set(key, value);
          else next.delete(key);
        }
        next.delete("cursor");
        setParams(next, { replace: true, preventScrollReset: true });
      }}
    >
      <label>
        Report status
        <select name="status" defaultValue={params.get("status") ?? ""}>
          <option value="">Any</option>
          {["pending", "verified", "rejected"].map((value) => (
            <option key={value}>{value}</option>
          ))}
        </select>
      </label>
      <label>
        Report evidence
        <select name="hasEvidence" defaultValue={params.get("hasEvidence") ?? ""}>
          <option value="">Any</option>
          <option value="true">Has active evidence</option>
          <option value="false">No active evidence</option>
        </select>
      </label>
      <label>
        Linked receipt lifecycle
        <select
          name="receiptLifecycleStatus"
          defaultValue={params.get("receiptLifecycleStatus") ?? ""}
        >
          <option value="">Any</option>
          <option value="active">Active</option>
          <option value="voided">Voided</option>
        </select>
      </label>
      <label>
        Received from
        <input type="date" name="receivedFrom" defaultValue={params.get("receivedFrom") ?? ""} />
      </label>
      <label>
        Received to
        <input type="date" name="receivedTo" defaultValue={params.get("receivedTo") ?? ""} />
      </label>
    </DynamicFilterForm>
  );
}
