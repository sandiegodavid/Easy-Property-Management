import { record, scalar } from "@epm/contracts/workflows";
import { label } from "./fields";

export function cents(value: number | string): string {
  const amount = BigInt(value),
    negative = amount < 0n,
    absolute = negative ? -amount : amount;
  return `${negative ? "-" : ""}${absolute / 100n}.${String(absolute % 100n).padStart(2, "0")}`;
}

export function MoneyFacts({ value, fields }: { value: unknown; fields: string[] }) {
  const item = record(value);
  return (
    <dl className="workflow-facts">
      {fields
        .filter((key) => key in item)
        .map((key) => (
          <div key={key}>
            <dt>{label(key)}</dt>
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
                        : scalar(item[key]).replaceAll("_", " ")}
            </dd>
          </div>
        ))}
    </dl>
  );
}
