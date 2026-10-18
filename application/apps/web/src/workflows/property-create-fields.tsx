import { fieldSchema, record, scalar, type RequestSchema } from "@epm/contracts/workflows";
import { Fields, type Choices } from "./fields";
import { PropertyEditFields } from "./property-edit-fields";
import { OwnershipFields } from "./ownership-fields";

function subset(schema: RequestSchema, keys: string[]): RequestSchema {
  return {
    ...schema,
    properties: Object.fromEntries(
      Object.entries(schema.properties ?? {}).filter(([key]) => keys.includes(key)),
    ),
  };
}

export function PropertyCreateFields({
  schema,
  value,
  onChange,
  choices,
  disabled,
  onAddingChange,
}: {
  schema: RequestSchema;
  value: Record<string, unknown>;
  onChange: (next: Record<string, unknown>) => void;
  choices: Choices;
  disabled: boolean;
  onAddingChange: (pending: boolean) => void;
}) {
  const rentals = Array.isArray(value.spaces) ? value.spaces.map(record) : [];
  const suites = value.inventoryLayout === "office_suites";
  const rentalSchema = fieldSchema(schema.properties?.spaces ?? {}).items ?? {};
  return (
    <>
      <PropertyEditFields
        schema={schema}
        value={value}
        onChange={onChange}
        disabled={disabled}
        creating
      />
      <fieldset className="property-create-section">
        <legend>Property type and rental layout</legend>
        <div className="property-create-layout">
          <label>
            Property type (required)
            <select
              disabled={disabled}
              value={scalar(value.propertyType, "")}
              onChange={(event) => {
                const next: Record<string, unknown> = {
                  ...value,
                  propertyType: event.target.value,
                };
                delete next.inventoryLayout;
                delete next.spaces;
                onChange(next);
              }}
            >
              <option value="single_family_home">Single-family home</option>
              <option value="condo">Condo</option>
              <option value="townhome">Townhome</option>
              <option value="office">Office</option>
            </select>
          </label>
          {value.propertyType === "office" && (
            <label>
              Rental layout
              <select
                disabled={disabled}
                value={scalar(value.inventoryLayout, "whole_office")}
                onChange={(event) => {
                  const next: Record<string, unknown> = {
                    ...value,
                    inventoryLayout: event.target.value,
                  };
                  if (event.target.value === "office_suites") next.spaces = [{ displayName: "" }];
                  else delete next.spaces;
                  onChange(next);
                }}
              >
                <option value="whole_office">One whole office</option>
                <option value="office_suites">Individually rented suites</option>
              </select>
            </label>
          )}
        </div>
        <p className="property-edit-hint">
          {suites
            ? "Add each independently rented suite. Each suite keeps its own occupancy, leasing status and leases."
            : value.propertyType === "office"
              ? "A whole-office rental is created automatically. You can update its name and status after saving."
              : "A whole-home rental is created automatically. You can record occupancy, leasing status and a lease after saving."}
        </p>
        {(suites || rentals.length > 0) &&
          rentals.map((rental, index) => (
            <fieldset key={index} className="property-create-child">
              <legend>{suites ? `Suite ${index + 1}` : "Rental details"}</legend>
              <Fields
                schema={subset(fieldSchema(rentalSchema), ["displayName", "suiteOrFloor", "notes"])}
                value={rental}
                disabled={disabled}
                onChange={(next) =>
                  onChange({
                    ...value,
                    spaces: rentals.map((item, position) =>
                      position === index ? record(next) : item,
                    ),
                  })
                }
              />
              <details>
                <summary>Initial occupancy and leasing status (optional)</summary>
                <Fields
                  schema={subset(fieldSchema(rentalSchema), ["occupancy", "availability"])}
                  value={rental}
                  disabled={disabled}
                  onChange={(next) =>
                    onChange({
                      ...value,
                      spaces: rentals.map((item, position) =>
                        position === index ? record(next) : item,
                      ),
                    })
                  }
                />
              </details>
              {suites && rentals.length > 1 && (
                <button
                  type="button"
                  disabled={disabled}
                  onClick={() =>
                    onChange({
                      ...value,
                      spaces: rentals.filter((_, position) => position !== index),
                    })
                  }
                >
                  Remove suite {index + 1}
                </button>
              )}
            </fieldset>
          ))}
        {suites && (
          <button
            type="button"
            disabled={disabled || rentals.length >= 100}
            onClick={() => onChange({ ...value, spaces: [...rentals, { displayName: "" }] })}
          >
            Add suite
          </button>
        )}
        {!suites && !rentals.length && (
          <details className="property-create-advanced">
            <summary>Customize the rental (optional)</summary>
            <button
              type="button"
              disabled={disabled}
              onClick={() =>
                onChange({
                  ...value,
                  spaces: [
                    {
                      displayName: value.propertyType === "office" ? "Whole office" : "Whole home",
                    },
                  ],
                })
              }
            >
              Customize rental details
            </button>
          </details>
        )}
      </fieldset>
      <OwnershipFields
        mode="create"
        value={value}
        onChange={onChange}
        choices={choices}
        disabled={disabled}
        onAddingChange={onAddingChange}
      />
    </>
  );
}
