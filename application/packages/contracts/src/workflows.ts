import definitions from "./generated/workflows.json" with { type: "json" };
import type { components } from "./generated/schema";
export { dispatchWorkflow } from "./generated/workflow-dispatch";

export type RequestSchema = {
  title?: string;
  type?: string;
  properties?: Record<string, RequestSchema>;
  required?: string[];
  items?: RequestSchema;
  anyOf?: RequestSchema[];
  oneOf?: RequestSchema[];
  enum?: (string | number)[];
  const?: string | number;
  format?: string;
  minimum?: number;
  maximum?: number;
  minLength?: number;
  maxLength?: number;
  minItems?: number;
  maxItems?: number;
  pattern?: string;
  default?: unknown;
  additionalProperties?: boolean | RequestSchema;
};
export type Workflow = {
  formKey: components["schemas"]["RecoveryInput"]["formKey"];
  title: string;
  method: string;
  path: string;
  sourceKind: components["schemas"]["RecoveryInput"]["sourceKind"];
  nesting: string | null;
  childKey: string | null;
  operationId: string;
  schema: RequestSchema;
};
export const workflows = definitions as unknown as Workflow[];
export function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}
export function scalar(value: unknown, fallback = ""): string {
  return typeof value === "string" || typeof value === "number" || typeof value === "boolean"
    ? String(value)
    : fallback;
}
export function fieldSchema(schema: RequestSchema): RequestSchema {
  return schema.anyOf?.find((item) => item.type !== "null") ?? schema;
}
export function validateRequest(schema: RequestSchema, value: unknown, name = "Request"): void {
  const choices = schema.anyOf ?? schema.oneOf;
  if (choices) {
    for (const choice of choices) {
      try {
        validateRequest(choice, value, name);
        return;
      } catch {
        /* Try the next declared type. */
      }
    }
    throw new Error(`${name} has an invalid value.`);
  }
  if (schema.type === "null" && value !== null) throw new Error(`${name} must be null.`);
  if (schema.type === "object") {
    if (value === null || typeof value !== "object" || Array.isArray(value))
      throw new Error(`${name} must be a record.`);
    const values = record(value);
    for (const key of schema.required ?? [])
      if (values[key] === undefined) throw new Error(`${name}: complete ${key}.`);
    for (const [key, item] of Object.entries(values)) {
      const child = schema.properties?.[key];
      if (!child && schema.additionalProperties === false)
        throw new Error(`${name}: unsupported field ${key}.`);
      if (child) validateRequest(child, item, `${name}.${key}`);
      else if (typeof schema.additionalProperties === "object")
        validateRequest(schema.additionalProperties, item, `${name}.${key}`);
    }
  }
  if (schema.type === "array") {
    if (!Array.isArray(value)) throw new Error(`${name} must be a list.`);
    if (value.length < (schema.minItems ?? 0) || value.length > (schema.maxItems ?? 100))
      throw new Error(`${name} has too many or too few entries.`);
    for (const item of value) if (schema.items) validateRequest(schema.items, item, name);
  }
  if (schema.type === "boolean" && typeof value !== "boolean")
    throw new Error(`${name} must be confirmed or cleared.`);
  if (schema.type === "integer" || schema.type === "number") {
    if (
      typeof value !== "number" ||
      !Number.isFinite(value) ||
      (schema.type === "integer" && !Number.isInteger(value)) ||
      value < (schema.minimum ?? -Infinity) ||
      value > (schema.maximum ?? Infinity)
    )
      throw new Error(`${name} has an invalid number.`);
  }
  if (schema.type === "string") {
    if (
      typeof value !== "string" ||
      value.length < (schema.minLength ?? 0) ||
      value.length > (schema.maxLength ?? Infinity)
    )
      throw new Error(`${name} has an invalid length.`);
    if (schema.pattern && !new RegExp(schema.pattern).test(value))
      throw new Error(`${name} has an invalid format.`);
    if (
      schema.format === "uuid" &&
      !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value)
    )
      throw new Error(`${name} must be a valid record identifier.`);
    if (
      schema.format === "date" &&
      (!/^\d{4}-\d{2}-\d{2}$/.test(value) ||
        !Number.isFinite(Date.parse(value)) ||
        new Date(value).toISOString().slice(0, 10) !== value)
    )
      throw new Error(`${name} must be a valid date.`);
  }
  if (schema.enum && !schema.enum.includes(value as string | number))
    throw new Error(`${name} must be one of the listed choices.`);
  if (schema.const !== undefined && schema.const !== value)
    throw new Error(`${name} has an invalid value.`);
}
