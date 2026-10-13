import { useState } from "react";
import { type RequestSchema, record } from "@epm/contracts/workflows";
import { Fields, type Choices } from "./fields";

export function TaskCreateFields({
  schema,
  value,
  onChange,
  choices,
  disabled,
}: {
  schema: RequestSchema;
  value: Record<string, unknown>;
  onChange: (value: Record<string, unknown>) => void;
  choices: Choices;
  disabled: boolean;
}) {
  const [noDate, setNoDate] = useState(!value.dueAtUtc && !value.dueTimezone);
  const timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  let dueDate = "";
  if (typeof value.dueAtUtc === "string") {
    try {
      const parts = new Intl.DateTimeFormat("en-US", {
        timeZone: typeof value.dueTimezone === "string" ? value.dueTimezone : timeZone,
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
      }).formatToParts(new Date(value.dueAtUtc));
      dueDate = ["year", "month", "day"]
        .map((part) => parts.find((item) => item.type === part)?.value)
        .join("-");
    } catch {
      // Retain incomplete advanced input for validation without breaking the form.
    }
  }
  function fields(keys: string[]) {
    return {
      ...schema,
      properties: Object.fromEntries(
        Object.entries(schema.properties ?? {}).filter(([key]) => keys.includes(key)),
      ),
    };
  }
  return (
    <>
      <Fields
        schema={fields(["title"])}
        value={value}
        onChange={(next) => onChange(record(next))}
        disabled={disabled}
      />
      <label>
        <input
          type="checkbox"
          checked={noDate}
          disabled={disabled}
          onChange={(event) => {
            setNoDate(event.target.checked);
            if (event.target.checked) {
              const next = { ...value };
              delete next.dueAtUtc;
              delete next.dueTimezone;
              next.isAllDay = false;
              onChange(next);
            }
          }}
        />
        No due date
      </label>
      {!noDate && (
        <>
          <label>
            Due date
            <input
              type="date"
              value={dueDate}
              disabled={disabled}
              required
              onChange={(event) => {
                if (!event.target.value) return;
                onChange({
                  ...value,
                  dueAtUtc: new Date(`${event.target.value}T00:00:00`).toISOString(),
                  dueTimezone: timeZone,
                  isAllDay: true,
                });
              }}
            />
          </label>
          <p>
            Date selection creates an all-day deadline in {timeZone}. Optional details allow an
            exact time or another time zone.
          </p>
        </>
      )}
      <details>
        <summary>Optional Task details</summary>
        <Fields
          schema={{
            ...schema,
            properties: Object.fromEntries(
              Object.entries(schema.properties ?? {}).filter(
                ([key]) =>
                  key !== "title" &&
                  (!noDate || !["dueAtUtc", "dueTimezone", "isAllDay"].includes(key)),
              ),
            ),
          }}
          value={value}
          onChange={(next) => onChange(record(next))}
          choices={choices}
          disabled={disabled}
        />
      </details>
    </>
  );
}
