import { useState } from "react";
import { fieldSchema, record, scalar, type RequestSchema } from "@epm/contracts/workflows";
import { Fields, type Choice, type Choices } from "./fields";
import { IdentityLookup } from "./reads";
import { PropertyEditFields } from "./property-edit-fields";

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
}: {
  schema: RequestSchema;
  value: Record<string, unknown>;
  onChange: (next: Record<string, unknown>) => void;
  choices: Choices;
  disabled: boolean;
}) {
  const [identities, setIdentities] = useState<Choice[]>([]);
  const owners = Array.isArray(value.ownerships) ? value.ownerships.map(record) : [];
  const rentals = Array.isArray(value.spaces) ? value.spaces.map(record) : [];
  const suites = value.inventoryLayout === "office_suites";
  const rentalSchema = fieldSchema(schema.properties?.spaces ?? {}).items ?? {};
  const ownerSchema = fieldSchema(schema.properties?.ownerships ?? {}).items ?? {};
  const replaceOwner = (index: number, next: Record<string, unknown>) =>
    onChange({
      ...value,
      ownerships: owners.map((owner, position) => (position === index ? next : owner)),
    });
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
      <fieldset className="property-create-section">
        <legend>Ownership</legend>
        <p className="property-edit-hint">
          Choose You for your own property, another owner for a managed property, or add multiple
          owners for co-ownership. Ownership does not set financial shares.
        </p>
        {owners.map((owner, index) => (
          <fieldset key={index} className="property-create-child">
            <legend>Owner {index + 1}</legend>
            <label>
              Owner
              <select
                disabled={disabled}
                value={scalar(owner.ownerKind, "local_operator")}
                onChange={(event) => replaceOwner(index, { ownerKind: event.target.value })}
              >
                <option value="local_operator">You</option>
                <option value="client_owner">Another owner</option>
              </select>
            </label>
            {owner.ownerKind === "client_owner" && (
              <Fields
                schema={subset(fieldSchema(ownerSchema), ["partyId", "inlineParty"])}
                value={owner}
                choices={{ ...choices, partyId: [...(choices.partyId ?? []), ...identities] }}
                disabled={disabled}
                onChange={(next) => replaceOwner(index, record(next))}
              />
            )}
            {owners.length > 1 && (
              <button
                type="button"
                disabled={disabled}
                onClick={() =>
                  onChange({
                    ...value,
                    ownerships: owners.filter((_, position) => position !== index),
                  })
                }
              >
                Remove owner {index + 1}
              </button>
            )}
          </fieldset>
        ))}
        <button
          type="button"
          disabled={disabled || owners.length >= 100}
          onClick={() =>
            onChange({ ...value, ownerships: [...owners, { ownerKind: "client_owner" }] })
          }
        >
          Add owner
        </button>
        <details className="property-create-advanced">
          <summary>Find an existing owner identity</summary>
          <IdentityLookup
            embedded
            onSelect={(id, name) =>
              setIdentities((current) => [
                ...current.filter((item) => item.id !== id),
                { id, label: name },
              ])
            }
          />
        </details>
      </fieldset>
    </>
  );
}
