import { useEffect, useRef } from "react";
import { fieldSchema, record, validateRequest, type RequestSchema } from "@epm/contracts/workflows";
import { label } from "./fields";

export function fieldName(path: string): string {
  const names: Record<string, string> = {
    propertyId: "Property",
    spaceId: "Rental unit",
    partyId: "Person or business",
    tenantPartyId: "Tenant",
    ownerId: "Owner",
    ownerPartyId: "Owner",
    providerPartyId: "Provider",
    payerPartyId: "Payer",
    paidByPartyId: "Paid by",
    leaseId: "Lease",
    expectationId: "Rent period",
    reportedAtUtc: "Reported time (include time-zone offset)",
  };
  return path
    .split(".")
    .filter((part) => !["Request", "body"].includes(part))
    .map((part) =>
      /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(part)
        ? "Participant"
        : /^\d+$/.test(part)
          ? `Item ${Number(part) + 1}`
          : (names[part] ?? label(part.replaceAll("_", " "))),
    )
    .join(" · ");
}

export function validateForm(schema: RequestSchema, value: unknown, name = "Your form"): void {
  const shape = fieldSchema(schema);
  if (shape.type === "array" && Array.isArray(value)) {
    validateRequest({ ...shape, items: undefined }, value, name);
    const errors: string[] = [];
    value.forEach((item, index) => {
      try {
        validateForm(shape.items ?? {}, item, `${name} ${index + 1}`);
      } catch (cause) {
        errors.push(
          cause instanceof Error ? cause.message : `Check ${name.toLowerCase()} ${index + 1}.`,
        );
      }
    });
    if (errors.length) throw new Error(errors.join("\n"));
    return;
  }
  if (shape.type !== "object" || value === null) return validateRequest(schema, value, name);
  const values = record(value);
  const errors: string[] = [];
  for (const [key, child] of Object.entries(shape.properties ?? {})) {
    const childName = name === "Your form" ? fieldName(key) : `${name} · ${fieldName(key)}`;
    if (values[key] === undefined) {
      if (shape.required?.includes(key)) errors.push(`Choose or enter ${childName.toLowerCase()}.`);
    } else {
      try {
        validateForm(child, values[key], childName);
      } catch (cause) {
        errors.push(
          cause instanceof Error ? cause.message : `Check ${fieldName(key).toLowerCase()}.`,
        );
      }
    }
  }
  if (errors.length) throw new Error(errors.join("\n"));
  validateRequest(schema, value, name);
}

export function FormFeedback({ message, focusKey = 0 }: { message?: string; focusKey?: number }) {
  const summary = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (message) {
      summary.current?.focus();
      summary.current?.scrollIntoView({ block: "center" });
    }
  }, [message, focusKey]);
  if (!message) return null;
  return (
    <div ref={summary} role="alert" tabIndex={-1} className="form-feedback">
      <strong>Please review your form</strong>
      <ul>
        {message.split("\n").map((item, index) => (
          <li key={index}>
            {item.replace(/\b(?:Request\.)?([a-z]+(?:[A-Z][a-z]+)+)\b/g, (key) => fieldName(key))}
          </li>
        ))}
      </ul>
    </div>
  );
}
