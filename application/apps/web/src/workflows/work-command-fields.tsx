import { record, type RequestSchema } from "@epm/contracts/workflows";
import { Fields, type Choices } from "./fields";

type Group = [string, string[], string?];
const groups: Record<string, Group[]> = {
  "maintenance.issue.start": [
    ["Start work", [], "Move this issue to In progress. This does not record a completed repair."],
  ],
  "maintenance.issue.resolve": [
    [
      "Resolution",
      ["reason", "confirmed"],
      "Describe how the issue was resolved. Finish or cancel scheduled appointments first.",
    ],
  ],
  "maintenance.issue.cancel": [
    [
      "Cancellation",
      ["reason", "confirmed"],
      "Explain why this issue is being cancelled. Its records and history remain available.",
    ],
  ],
  "maintenance.appointment.create": [
    [
      "Appointment",
      ["purpose", "startsAtUtc", "endsAtUtc"],
      "Include a time-zone offset in each time. Times are reviewed in the property's time zone.",
    ],
    ["Access and preparation", ["instructions"]],
  ],
  "maintenance.quote.create": [
    ["Provider and offer", ["providerPartyId", "label", "receivedOn"]],
    [
      "Scope and price",
      ["scopeSummary", "amount"],
      "Record the provider's quoted price in USD, for example 125.00. This is not a paid expense.",
    ],
    [
      "Proposed schedule and terms",
      [
        "earliestWorkStartOn",
        "estimatedWorkFinishOn",
        "validThrough",
        "termsNotes",
        "replacesQuoteId",
      ],
    ],
  ],
  "maintenance.assignment.create": [
    [
      "Provider selection",
      ["providerPartyId", "quoteId", "selectionReason", "directAssignmentConfirmed"],
    ],
    ["Work instructions", ["instructions"]],
    [
      "Replacement and selection review",
      [
        "replacesAssignmentId",
        "replacementConfirmed",
        "endReason",
        "avoidOverrideConfirmed",
        "avoidOverrideReason",
      ],
    ],
  ],
  "maintenance.cost.create": [
    [
      "Cost information",
      ["contextKind", "label", "amount", "observedOn"],
      "Use USD, for example 125.00. Estimates and reported costs are context, not money paid.",
    ],
    ["Source and corrections", ["sourceNote", "replacesCostContextId"]],
  ],
  "maintenance.expense.link": [
    [
      "Paid expense",
      ["expenseId"],
      "Choose an existing paid expense for this property. Linking it does not record another payment.",
    ],
  ],
  "maintenance.follow_up.create": [
    ["Follow-up task", ["title", "notes", "priority"]],
    [
      "Deadline",
      ["dueAtUtc", "dueTimezone"],
      "A deadline and its IANA time zone must be supplied together. Completing this task does not resolve the issue.",
    ],
  ],
  "maintenance.journal.record": [
    [
      "Work entry",
      ["entryKind", "sourceKind", "assignmentId", "occurredAtUtc", "summary", "detail"],
    ],
    [
      "Work outcome",
      ["outcomeStatus", "outcomeSummary", "operatorVerified", "followUpRequired"],
      "Complete these fields for a Work completed entry. Provider-reported completion is not operator verification.",
    ],
    [
      "Correction or historical entry",
      ["correctsEntryId", "correctedEntryKind", "correctionReason", "historicalEntryConfirmed"],
    ],
  ],
  "maintenance.quote.withdraw": [
    [
      "Withdraw quote",
      ["reason", "confirmed"],
      "The original quote and supporting documents remain in history.",
    ],
  ],
  "communication.create": [
    ["Conversation", ["subject", "body", "channel", "direction"]],
    ["When it happened", ["occurredAtUtc", "occurredTimezone"]],
    ["People and related records", ["participants", "links"]],
    [
      "Record and follow up",
      ["record", "followUp"],
      "This records an interaction; it never sends a message. A follow-up task is managed separately.",
    ],
  ],
  "file.upload": [
    [
      "Attachment purpose",
      ["purpose"],
      "Attach supporting evidence to this maintenance issue. Files must be no larger than 50 MiB.",
    ],
  ],
};

export function hasWorkCommandFields(key: string) {
  return key in groups;
}

export function WorkCommandFields({
  formKey,
  schema,
  value,
  onChange,
  choices,
  disabled,
}: {
  formKey: string;
  schema: RequestSchema;
  value: Record<string, unknown>;
  onChange: (value: unknown) => void;
  choices: Choices;
  disabled: boolean;
}) {
  return (
    <div className="tidy-form-sections">
      {groups[formKey]?.map(([title, keys, hint]) => {
        const effectiveKind =
          value.entryKind === "correction" ? value.correctedEntryKind : value.entryKind;
        if (
          formKey === "maintenance.journal.record" &&
          title === "Work outcome" &&
          effectiveKind !== "work_completed"
        )
          return null;
        const visible = keys.filter(
          (key) =>
            !(
              formKey === "maintenance.journal.record" &&
              value.entryKind !== "correction" &&
              ["correctsEntryId", "correctedEntryKind", "correctionReason"].includes(key)
            ) &&
            !(
              key === "links" &&
              Array.isArray(value.links) &&
              value.links.length === 1 &&
              record(value.links[0]).entityType === "maintenance_issue"
            ),
        );
        const collapsible = title === "Replacement and selection review";
        const Container = collapsible ? "details" : "section";
        return (
          <Container
            className="tidy-form-section"
            aria-label={title}
            key={title}
            {...(collapsible
              ? {
                  open:
                    keys.some((key) => !!value[key]) || value.directAssignmentConfirmed === true,
                }
              : {})}
          >
            {collapsible ? <summary>{title}</summary> : <h3>{title}</h3>}
            {hint && <p className="record-detail-note">{hint}</p>}
            <div className="tidy-form-grid">
              <Fields
                schema={{
                  ...schema,
                  properties: Object.fromEntries(
                    visible
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
                  amount: "Amount (USD)",
                  providerPartyId: "Provider",
                  quoteId: "Quote",
                  expenseId: "Paid expense",
                  assignmentId: "Provider assignment",
                  replacesAssignmentId: "Previous assignment",
                  replacesQuoteId: "Original quote",
                  replacesCostContextId: "Previous cost record",
                  correctsEntryId: "Entry being corrected",
                }}
              />
            </div>
          </Container>
        );
      })}
    </div>
  );
}
