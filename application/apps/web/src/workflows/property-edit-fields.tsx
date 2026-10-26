import { fieldSchema, type RequestSchema } from "@epm/contracts/workflows";
import { useId } from "react";
import { label } from "./fields";
import { usStateCode, usStates } from "../shared/us-states";

export function PropertyEditFields({
  schema,
  value,
  onChange,
  disabled,
  creating = false,
}: {
  schema: RequestSchema;
  value: Record<string, unknown>;
  onChange: (next: Record<string, unknown>) => void;
  disabled: boolean;
  creating?: boolean;
}) {
  const stateId = useId();
  return (
    <div className="property-edit-groups">
      {[
        { title: "Property name", fields: ["displayName"] },
        {
          title: "Address",
          fields: ["addressLine1", "addressLine2", "city", "region", "postalCode"],
        },
        { title: "Notes", fields: ["notes"] },
      ].map((group) => (
        <fieldset key={group.title} className="property-edit-group">
          <legend>{group.title}</legend>
          {group.fields.map((key) => {
            const shape = fieldSchema(schema.properties?.[key] ?? {});
            const current = typeof value[key] === "string" ? value[key] : "";
            const update = (next: string) =>
              onChange({
                ...value,
                [key]:
                  next === "" && ["addressLine2", "region", "postalCode", "notes"].includes(key)
                    ? null
                    : next,
              });
            if (key === "region") {
              const selectedState = usStateCode(current);
              return (
                <div key={key} className="workflow-field">
                  <label htmlFor={stateId}>State</label>
                  <select
                    id={stateId}
                    name="region"
                    value={selectedState}
                    disabled={disabled}
                    autoComplete="address-level1"
                    onChange={(event) => update(event.target.value)}
                  >
                    <option value="">Choose a state</option>
                    {current && !usStates.some(([code]) => code === selectedState) && (
                      <option value={current}>{current} (current value)</option>
                    )}
                    {usStates.map(([code, name]) => (
                      <option key={code} value={code}>
                        {name}
                      </option>
                    ))}
                  </select>
                </div>
              );
            }
            return (
              <div key={key} className="workflow-field">
                <label>
                  {label(key)}
                  {creating && schema.required?.includes(key) && " (required)"}
                  {key === "notes" ? (
                    <textarea
                      value={current}
                      disabled={disabled}
                      maxLength={shape.maxLength}
                      onChange={(event) => update(event.target.value)}
                    />
                  ) : (
                    <input
                      value={current}
                      disabled={disabled}
                      maxLength={shape.maxLength}
                      required={["displayName", "addressLine1", "city", "countryCode"].includes(
                        key,
                      )}
                      onChange={(event) => update(event.target.value)}
                    />
                  )}
                </label>
              </div>
            );
          })}
        </fieldset>
      ))}
    </div>
  );
}
