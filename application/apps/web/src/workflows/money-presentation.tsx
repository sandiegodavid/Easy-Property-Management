import { record, scalar } from "@epm/contracts/workflows";
import { label } from "./fields";
import { formatHomeTime } from "../shared/home-time";
import { formatDate, formatUsd } from "../shared/presentation";

export function cents(value: number | string | bigint): string {
  const amount = BigInt(value),
    negative = amount < 0n,
    absolute = negative ? -amount : amount;
  return `${negative ? "-" : ""}${absolute / 100n}.${String(absolute % 100n).padStart(2, "0")}`;
}

type FactKind = "amount" | "status" | "plain";

function factDisplay(key: string, raw: unknown): { text: string; kind: FactKind } {
  if (raw === null || raw === undefined) return { text: "Not recorded", kind: "plain" };
  if (key.endsWith("Minor") && typeof raw === "number")
    return { text: formatUsd(cents(raw)), kind: "amount" };
  if (typeof raw === "string" && /^-?\d+\.\d{2}$/.test(raw))
    return { text: formatUsd(raw), kind: "amount" };
  if (typeof raw === "string" && /^\d{4}-\d\d-\d\d$/.test(raw))
    return { text: formatDate(raw), kind: "plain" };
  if (typeof raw === "boolean") return { text: raw ? "Yes" : "No", kind: "plain" };
  if (Array.isArray(raw))
    return {
      text: raw.filter((value): value is string => typeof value === "string").join("; ") || "None",
      kind: "plain",
    };
  if (typeof raw === "string" && /^\d{4}-\d\d-\d\dT.*(?:Z|[+-]\d\d:\d\d)$/.test(raw))
    return { text: formatHomeTime(raw), kind: "plain" };
  if (/(?:Status|Kind)$/.test(key) || ["status", "paymentFrequency", "decision"].includes(key))
    return { text: label(scalar(raw).replaceAll("_", " ")), kind: "status" };
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
      {[...new Set(fields)]
        .filter((key) => key !== "amount" || item.amountMinor == null)
        .filter((key) => item[key] != null && !/(?:^id$|Ids?$|Revision$)/.test(key))
        .map((key) => {
          const display = factDisplay(key, item[key]);
          return (
            <div key={key}>
              <dt>{labels?.[key] ?? label(key.replace(/Minor$/, ""))}</dt>
              <dd className={display.kind === "amount" ? "workflow-fact-amount" : undefined}>
                {display.kind === "status" ? (
                  <span className="workflow-fact-status" data-status={scalar(item[key])}>
                    {display.text}
                  </span>
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
