import { record, scalar } from "@epm/contracts/workflows";
import { label } from "./fields";

export function cents(value: number | string | bigint): string {
  const amount = BigInt(value),
    negative = amount < 0n,
    absolute = negative ? -amount : amount;
  return `${negative ? "-" : ""}${absolute / 100n}.${String(absolute % 100n).padStart(2, "0")}`;
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
        .map((key) => (
          <div key={key}>
            <dt>{labels?.[key] ?? label(key)}</dt>
            <dd>
              {item[key] == null
                ? "Not recorded"
                : key.endsWith("Minor") && typeof item[key] === "number"
                  ? `USD ${cents(item[key])}`
                  : typeof item[key] === "string" && /^-?\d+\.\d{2}$/.test(item[key])
                    ? `USD ${item[key]}`
                    : typeof item[key] === "boolean"
                      ? item[key]
                        ? "Yes"
                        : "No"
                      : Array.isArray(item[key])
                        ? item[key]
                            .filter((value): value is string => typeof value === "string")
                            .join("; ") || "None"
                        : /(?:Status|Kind)$/.test(key) ||
                            ["status", "paymentFrequency", "decision"].includes(key)
                          ? scalar(item[key]).replaceAll("_", " ")
                          : scalar(item[key])}
            </dd>
          </div>
        ))}
    </dl>
  );
}
