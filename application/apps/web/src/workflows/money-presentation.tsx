import { record, scalar } from "@epm/contracts/workflows";
import { label } from "./fields";

export function cents(value: number | string | bigint): string {
  const amount = BigInt(value),
    negative = amount < 0n,
    absolute = negative ? -amount : amount;
  return `${negative ? "-" : ""}${absolute / 100n}.${String(absolute % 100n).padStart(2, "0")}`;
}

const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

type FactKind = "amount" | "status" | "id" | "plain";

function factDisplay(key: string, raw: unknown): { text: string; kind: FactKind } {
  if (raw === null || raw === undefined) return { text: "Not recorded", kind: "plain" };
  if (key.endsWith("Minor") && typeof raw === "number")
    return { text: `USD ${cents(raw)}`, kind: "amount" };
  if (typeof raw === "string" && /^-?\d+\.\d{2}$/.test(raw))
    return { text: `USD ${raw}`, kind: "amount" };
  if (typeof raw === "boolean") return { text: raw ? "Yes" : "No", kind: "plain" };
  if (Array.isArray(raw))
    return {
      text:
        raw.filter((value): value is string => typeof value === "string").join("; ") || "None",
      kind: "plain",
    };
  if (typeof raw === "string" && uuidPattern.test(raw) && (key.endsWith("Id") || key === "id"))
    return { text: raw, kind: "id" };
  if (/(?:Status|Kind)$/.test(key) || ["status", "paymentFrequency", "decision"].includes(key))
    return { text: scalar(raw).replaceAll("_", " "), kind: "status" };
  return { text: scalar(raw), kind: "plain" };
}

export function MoneyFacts({
  value,
  fields,
  labels,
}: {
  value: unknown;
  fields: string[];
  labels?: Record<string, string>;
}) {
  const item = record(value);
  return (
    <dl className="workflow-facts">
      {fields
        .filter((key) => key in item)
        .map((key) => {
          const display = factDisplay(key, item[key]);
          return (
            <div key={key}>
              <dt>{labels?.[key] ?? label(key)}</dt>
              <dd className={display.kind === "amount" ? "workflow-fact-amount" : undefined}>
                {display.kind === "status" ? (
                  <span className="workflow-fact-status" data-status={scalar(item[key])}>
                    {display.text}
                  </span>
                ) : display.kind === "id" ? (
                  <span className="workflow-fact-id">{display.text}</span>
                ) : (
                  display.text
                )}
              </dd>
            </div>
          );
        })}
    </dl>
  );
}
