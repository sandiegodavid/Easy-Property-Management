import { fieldSchema, type RequestSchema } from "@epm/contracts/workflows";
import { label } from "./fields";

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
            return (
              <div key={key} className="workflow-field">
                <label>
                  {key === "region" ? "State" : label(key)}
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
