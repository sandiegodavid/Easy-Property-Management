import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { api } from "@epm/contracts";
import { record, scalar } from "@epm/contracts/workflows";
import { useWorkspace } from "../app/workspace-gate";
import { Facts, readResult } from "./reads";

export function MaintenanceContext({
  formKey,
  values,
  source,
}: {
  formKey: string;
  values: Record<string, unknown>;
  source: Record<string, unknown>;
}) {
  const { scope } = useWorkspace();
  const propertyId = scalar(source.propertyId ?? values.propertyId, "");
  const property = useQuery({
    queryKey: scope.key("maintenance-property-clock", propertyId),
    enabled: !!propertyId,
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/properties/{property_id}", {
          signal,
          params: { path: { property_id: propertyId } },
        }),
      ),
  });
  return (
    <section aria-label="Maintenance command review">
      <h3>Review the physical issue and independent records</h3>
      {property.data && (
        <Facts value={property.data} fields={["displayName", "timeZone", "effectiveLocalDate"]} />
      )}
      {property.error && (
        <p role="alert">
          Property context unavailable. The server still validates source membership and time zone.
        </p>
      )}
      <p>
        Reported and appointment instants must include an offset. The Property IANA zone controls
        local presentation, not your browser clock. Space selection must belong to that Property;
        Property and Space cannot be moved by editing an issue.
      </p>
      <Facts
        value={source}
        fields={["status", "revision", "reportedTimezone", "resolutionSummary"]}
      />
      <p>
        Issue status, appointment completion, reported work and operator-verified repair are
        separate facts. Resolving requires explicit confirmation and a summary; finish or cancel
        scheduled appointments first. Urgent classification does not contact emergency services.
      </p>
      {formKey.includes("appointment") && (
        <p>
          Scheduling does not create a calendar event or a mirrored Task. Rescheduling preserves the
          previous times and requires a reason; completing the appointment never resolves the issue.
        </p>
      )}
      {formKey.includes("cost.") && (
        <>
          <p>
            Operator estimate and work-reported amounts are non-financial context, not money paid.
            They are never added to Finance totals or summed here; confirm actual spending only in
            Finance.
          </p>
          {values.replacesCostContextId && (
            <Facts
              value={record(
                (Array.isArray(source.costContexts) ? source.costContexts : []).find(
                  (item) => record(item).id === values.replacesCostContextId,
                ),
              )}
              fields={["contextKind", "label", "amountMinor", "voidedAt"]}
            />
          )}
        </>
      )}
      {formKey.includes("expense.") && (
        <p>
          Select an existing paid Finance Expense from this Property. Linking stores a relationship
          only, not a copied amount; archiving it does not void, refund or rewrite that Expense. One
          Expense can have only one active issue association.
        </p>
      )}
      {formKey.includes("follow_up") && (
        <p>
          This creates one independently managed Task. Completing it does not verify a repair or
          resolve this issue; issue changes do not complete it automatically.
        </p>
      )}
      <p>
        Descriptions, access instructions, outcomes and reasons are sensitive contextual history.
        Evidence upload is separate: an attachment failure must leave the truthful issue or child
        record saved.
      </p>
    </section>
  );
}

export function MaintenanceFilters() {
  const [params] = useSearchParams();
  return (
    <>
      <label>
        Reporter role
        <select name="reporterRole" defaultValue={params.get("reporterRole") ?? ""}>
          <option value="">Any</option>
          {["owner", "tenant", "manager", "staff"].map((role) => (
            <option key={role}>{role}</option>
          ))}
        </select>
      </label>
      <label>
        Reporter subject
        <select name="reporterSubjectKind" defaultValue={params.get("reporterSubjectKind") ?? ""}>
          <option value="">Any</option>
          <option value="party">Party</option>
          <option value="local_operator">Local operator</option>
        </select>
      </label>
      <label>
        Reporter Party ID
        <input
          name="reporterPartyId"
          maxLength={36}
          defaultValue={params.get("reporterPartyId") ?? ""}
        />
      </label>
      <label>
        Issue category
        <select name="category" defaultValue={params.get("category") ?? ""}>
          <option value="">Any</option>
          {[
            "plumbing",
            "electrical",
            "heating_cooling",
            "appliance",
            "structural",
            "safety_security",
            "pest",
            "exterior_grounds",
            "cleaning",
            "other",
          ].map((value) => (
            <option key={value} value={value}>
              {value.replaceAll("_", " ")}
            </option>
          ))}
        </select>
      </label>
      <label>
        Issue priority
        <select name="priority" defaultValue={params.get("priority") ?? ""}>
          <option value="">Any</option>
          {["low", "normal", "high", "urgent"].map((value) => (
            <option key={value}>{value}</option>
          ))}
        </select>
      </label>
      <label>
        Space ID
        <input name="spaceId" maxLength={36} defaultValue={params.get("spaceId") ?? ""} />
      </label>
      {[
        ["hasEvidence", "Issue evidence"],
        ["hasLinkedExpense", "Linked paid Expense"],
        ["hasActiveTask", "Active follow-up Task"],
      ].map(([key, title]) => (
        <label key={key}>
          {title}
          <select name={key} defaultValue={params.get(key) ?? ""}>
            <option value="">Any</option>
            <option value="true">Yes</option>
            <option value="false">No</option>
          </select>
        </label>
      ))}
      {[
        ["reportedFrom", "Reported from (aware instant)"],
        ["reportedTo", "Reported to (aware instant)"],
        ["appointmentFrom", "Appointment from (aware instant)"],
        ["appointmentTo", "Appointment to (aware instant)"],
      ].map(([key, title]) => (
        <label key={key}>
          {title}
          <input
            name={key}
            maxLength={40}
            placeholder="2026-10-13T12:00:00-07:00"
            defaultValue={params.get(key) ?? ""}
          />
        </label>
      ))}
    </>
  );
}
