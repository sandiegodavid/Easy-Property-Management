import type { RequestSchema } from "@epm/contracts/workflows";
import { Fields, type Choices } from "./fields";
import { reporterChanged } from "./reporter-context";

export function GroupedCommandFields({
  schema,
  value,
  onChange,
  choices,
  disabled,
  formKey,
  originalReporter,
}: {
  schema: RequestSchema;
  value: Record<string, unknown>;
  onChange: (value: unknown) => void;
  choices: Choices;
  disabled: boolean;
  formKey: string;
  originalReporter?: unknown;
}) {
  const issue = formKey === "maintenance.issue.patch";
  const groups: [string, string[], string?][] = issue
    ? [
        ["Issue details", ["summary", "description"]],
        [
          "Category and priority",
          ["category", ...(value.category === "other" ? ["categoryDetail"] : []), "priority"],
        ],
        [
          "Reporter",
          [
            "reporter",
            ...(reporterChanged(value, originalReporter) ? ["reporterCorrectionReason"] : []),
          ],
          "Correct the person or role recorded for the original report. A changed reporter requires a reason.",
        ],
      ]
    : [
        [
          "Category details",
          ["displayName", "description", "displayOrder"],
          "Use a clear name for grouping paid expenses. Display order controls its position in the category list.",
        ],
      ];
  const used = new Set([
    ...groups.flatMap(([, keys]) => keys),
    "expectedRevision",
    "idempotencyKey",
    ...(issue ? ["categoryDetail", "reporterCorrectionReason"] : []),
  ]);
  const remaining = Object.keys(schema.properties ?? {}).filter((key) => !used.has(key));
  function fields(keys: string[]) {
    return (
      <Fields
        schema={{
          ...schema,
          required: [...(schema.required ?? []), ...(issue ? ["reporter"] : [])],
          properties: Object.fromEntries(
            keys
              .filter((key) => schema.properties?.[key])
              .map((key) => [key, schema.properties![key]]),
          ),
        }}
        value={
          issue
            ? Object.fromEntries(
                Object.entries(value).map(([key, current]) => [key, current ?? ""]),
              )
            : value
        }
        onChange={(next) => {
          if (!issue || !next || typeof next !== "object") return onChange(next);
          const edited = { ...next } as Record<string, unknown>;
          if ((edited.category && edited.category !== "other") || edited.categoryDetail === "")
            edited.categoryDetail = null;
          if (!reporterChanged(edited, originalReporter)) delete edited.reporterCorrectionReason;
          onChange(edited);
        }}
        choices={choices}
        disabled={disabled}
        showChangeControls={!issue && formKey.endsWith(".patch")}
        compactChangeControls
      />
    );
  }
  return (
    <div className="tidy-form-sections">
      {groups.map(([title, keys, hint]) => (
        <section className="tidy-form-section" key={title} aria-label={title}>
          <h3>{title}</h3>
          {hint && <p className="record-detail-note">{hint}</p>}
          <div className="tidy-form-grid">{fields(keys)}</div>
        </section>
      ))}
      {remaining.length > 0 && (
        <details
          className="tidy-form-section"
          open={remaining.some(
            (key) => value[key] != null && value[key] !== "" && value[key] !== false,
          )}
        >
          <summary>Additional details and duplicate review</summary>
          {fields(remaining)}
        </details>
      )}
    </div>
  );
}
