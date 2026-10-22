import { type RequestSchema } from "@epm/contracts/workflows";
import { Fields, type Choices } from "./fields";

export function MaintenanceCreateFields({
  schema,
  value,
  onChange,
  choices,
  disabled,
  concern,
}: {
  schema: RequestSchema;
  value: Record<string, unknown>;
  onChange: (value: unknown) => void;
  choices?: Choices;
  disabled: boolean;
  concern: boolean;
}) {
  const groups: [string, string[]][] = [
    [
      "Property and people",
      [
        "propertyId",
        "spaceId",
        ...(concern ? ["ownerPartyId", "concernType", "leaseId", "tenantPartyId"] : []),
      ],
    ],
    [
      concern ? "Concern details" : "Issue details",
      ["summary", "description", "category", "categoryDetail", "priority"],
    ],
    ...(!concern ? ([["Reported by", ["reporter"]]] as [string, string[]][]) : []),
  ];
  const used = new Set(groups.flatMap(([, keys]) => keys));
  const remaining = Object.keys(schema.properties ?? {}).filter(
    (key) => !used.has(key) && !["expectedRevision", "idempotencyKey"].includes(key),
  );
  function fields(keys: string[]) {
    return (
      <Fields
        schema={{
          ...schema,
          properties: Object.fromEntries(
            keys
              .filter((key) => schema.properties?.[key])
              .map((key) => [key, schema.properties![key]]),
          ),
        }}
        value={value}
        onChange={onChange}
        choices={choices}
        disabled={disabled}
        showChangeControls={false}
        fieldLabels={{
          propertyId: "Property",
          spaceId: "Home, unit or suite (optional)",
          ownerPartyId: "Owner",
          tenantPartyId: "Tenant",
          leaseId: "Lease",
          subjectKind: "Reported by",
          partyId: "Reporter",
          role: "Reporter role",
        }}
      />
    );
  }
  return (
    <div className="maintenance-create-sections">
      {groups.map(([title, keys]) => (
        <section key={title} aria-label={title} className="maintenance-create-section">
          <h3>{title}</h3>
          <div className="maintenance-create-grid">{fields(keys)}</div>
        </section>
      ))}
      {remaining.length > 0 && (
        <details className="maintenance-create-section">
          <summary>Follow-up and additional context</summary>
          {fields(remaining)}
        </details>
      )}
    </div>
  );
}
