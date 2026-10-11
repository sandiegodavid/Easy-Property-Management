import { fieldSchema, record, type RequestSchema } from "@epm/contracts/workflows";

export type Choice = { id: string; label: string; revision?: number };
export type Choices = Record<string, Choice[]>;
export function label(name: string) {
  const overrides: Record<string, string> = {
    displayName: "Display name",
    confirmed: "I confirm this lifecycle change",
    confirmedNewParty: "I reviewed possible duplicates and confirm this is a new identity",
    doNotContact: "Do not contact",
    partyId: "Existing identity",
    inlineParty: "Create owner identity here",
    expectedTenantRevision: "Displayed Tenant revision",
    expectedCategoryRevision: "Displayed category revision",
    referenceResolutions: "Resolve contact references",
    clear: "Clear this preference",
    ownerKind: "Ownership kind",
    partyKind: "Identity kind",
    effectiveOn: "Effective date",
  };
  return (
    overrides[name] ??
    name
      .replace(/([A-Z])/g, (letter) => ` ${letter.toLowerCase()}`)
      .replace(/^./, (letter) => letter.toUpperCase())
  );
}
export function seed(schema: RequestSchema): unknown {
  const shape = fieldSchema(schema);
  if (shape.default !== undefined) return shape.default;
  if (shape.type === "object") return {};
  if (shape.type === "array") return [];
  if (shape.type === "boolean") return false;
  return "";
}
export function clean(schema: RequestSchema, value: unknown): unknown {
  const shape = fieldSchema(schema);
  if (value === undefined || value === "") return undefined;
  if (value === null) return null;
  if (shape.type === "object")
    return Object.fromEntries(
      Object.entries(record(value))
        .filter(([key]) => !!shape.properties?.[key])
        .map(([key, child]) => [key, clean(shape.properties![key], child)])
        .filter(([, child]) => child !== undefined),
    );
  if (shape.type === "array" && Array.isArray(value))
    return value.map((child) => clean(shape.items ?? {}, child));
  return value;
}

export function Fields({
  schema,
  value,
  onChange,
  path = "",
  choices = {},
  disabled = false,
}: {
  schema: RequestSchema;
  value: unknown;
  onChange: (value: unknown) => void;
  path?: string;
  choices?: Choices;
  disabled?: boolean;
}) {
  const shape = fieldSchema(schema);
  if (shape.type !== "object") return null;
  const values = record(value);
  return (
    <>
      {Object.entries(shape.properties ?? {})
        .filter(
          ([key]) =>
            ![
              "expectedRevision",
              "expectedLeaseRevision",
              "expectedPropertyRevision",
              "idempotencyKey",
              "expectedRentLedgerRevision",
            ].includes(key),
        )
        .map(([key, child]) => {
          const current = values[key],
            childShape = fieldSchema(child),
            name = /^[0-9a-f-]{36}$/.test(key) ? (childShape.title ?? label(key)) : label(key);
          const fieldPath = path ? `${path}.${key}` : key;
          const update = (next: unknown) => {
            const replacement = { ...values };
            if (key === "partyId" && next) delete replacement.inlineParty;
            if (key === "inlineParty" && next) delete replacement.partyId;
            if (key === "ownerKind" && next === "local_operator") {
              delete replacement.partyId;
              delete replacement.inlineParty;
            }
            if (next === undefined) delete replacement[key];
            else replacement[key] = next;
            onChange(replacement);
          };
          const nullable = child.anyOf?.some((item) => item.type === "null");
          const options = choices[key];
          if ((key === "partyId" || key === "inlineParty") && values.ownerKind === "local_operator")
            return null;
          if (childShape.type === "object")
            return (
              <fieldset key={key}>
                <legend>{name}</legend>
                {current === undefined ? (
                  <button type="button" disabled={disabled} onClick={() => update(seed(child))}>
                    Add {name.toLowerCase()}
                  </button>
                ) : (
                  <>
                    <Fields
                      schema={childShape}
                      value={current}
                      onChange={update}
                      path={fieldPath}
                      choices={choices}
                      disabled={disabled}
                    />
                    {!shape.required?.includes(key) && (
                      <button type="button" disabled={disabled} onClick={() => update(undefined)}>
                        Omit {name.toLowerCase()}
                      </button>
                    )}
                  </>
                )}
              </fieldset>
            );
          if (childShape.type === "array") {
            const items: unknown[] = Array.isArray(current) ? current : [];
            return (
              <fieldset key={key}>
                <legend>{name}</legend>
                {items.map((item, index) => (
                  <fieldset key={index}>
                    <legend>
                      {name} {index + 1}
                    </legend>
                    {fieldSchema(childShape.items ?? {}).type === "object" ? (
                      <Fields
                        schema={childShape.items ?? {}}
                        value={item}
                        onChange={(next) =>
                          update(items.map((old, position) => (position === index ? next : old)))
                        }
                        path={`${fieldPath}.${index}`}
                        choices={choices}
                        disabled={disabled}
                      />
                    ) : (
                      <label>
                        {name} {index + 1}
                        <select
                          value={typeof item === "string" ? item : ""}
                          disabled={disabled}
                          onChange={(event) =>
                            update(
                              items.map((old, position) =>
                                position === index ? event.target.value : old,
                              ),
                            )
                          }
                        >
                          <option value="">Choose…</option>
                          {(options ?? []).map((option) => (
                            <option key={option.id} value={option.id}>
                              {option.label}
                            </option>
                          ))}
                        </select>
                      </label>
                    )}
                    <button
                      type="button"
                      disabled={disabled}
                      onClick={() => update(items.filter((_, position) => position !== index))}
                    >
                      Remove {name.toLowerCase()} {index + 1}
                    </button>
                  </fieldset>
                ))}
                <button
                  type="button"
                  disabled={disabled || items.length >= Math.min(childShape.maxItems ?? 100, 100)}
                  onClick={() => update([...items, seed(childShape.items ?? {})])}
                >
                  Add {name.toLowerCase()} entry
                </button>
              </fieldset>
            );
          }
          return (
            <div className="workflow-field" key={key}>
              {childShape.type === "boolean" ? (
                <label>
                  <input
                    type="checkbox"
                    disabled={disabled}
                    checked={current === true}
                    onChange={(event) => update(event.target.checked)}
                  />
                  {name}
                </label>
              ) : (
                <label>
                  {name}
                  {shape.required?.includes(key) && " (required)"}
                  {childShape.enum || options ? (
                    <select
                      disabled={disabled || current === null}
                      value={typeof current === "string" ? current : ""}
                      onChange={(event) => {
                        const selected = event.target.value;
                        if (key === "categoryId") {
                          const choice = options?.find((item) => item.id === selected);
                          onChange({
                            ...values,
                            categoryId: selected,
                            expectedCategoryRevision: choice?.revision,
                          });
                        } else update(selected);
                      }}
                    >
                      <option value="">Choose…</option>
                      {childShape.enum
                        ? childShape.enum.map((option) => (
                            <option key={option} value={option}>
                              {String(option).replaceAll("_", " ")}
                            </option>
                          ))
                        : options?.map((option) => (
                            <option key={option.id} value={option.id}>
                              {option.label}
                            </option>
                          ))}
                    </select>
                  ) : childShape.maxLength && childShape.maxLength > 500 ? (
                    <textarea
                      disabled={disabled || current === null}
                      maxLength={childShape.maxLength}
                      value={typeof current === "string" ? current : ""}
                      onChange={(event) => update(event.target.value)}
                    />
                  ) : (
                    <input
                      disabled={disabled || current === null}
                      type={
                        childShape.type === "integer"
                          ? "number"
                          : childShape.format === "date"
                            ? "date"
                            : "text"
                      }
                      min={childShape.minimum}
                      max={childShape.maximum}
                      maxLength={childShape.maxLength}
                      value={
                        typeof current === "string" || typeof current === "number" ? current : ""
                      }
                      onChange={(event) =>
                        update(
                          childShape.type === "integer" && event.target.value !== ""
                            ? Number(event.target.value)
                            : event.target.value,
                        )
                      }
                    />
                  )}
                </label>
              )}
              {nullable && (
                <label>
                  <input
                    type="checkbox"
                    disabled={disabled}
                    checked={current === null}
                    onChange={(event) => update(event.target.checked ? null : undefined)}
                  />
                  Clear {name.toLowerCase()}
                </label>
              )}
              {!shape.required?.includes(key) && current !== undefined && current !== null && (
                <button type="button" disabled={disabled} onClick={() => update(undefined)}>
                  Leave {name.toLowerCase()} unchanged / omit
                </button>
              )}
            </div>
          );
        })}
    </>
  );
}
