import { record } from "@epm/contracts/workflows";

export function ownershipShareLabel(value: unknown) {
  return value === null || value === undefined || value === ""
    ? "Not recorded"
    : `${Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 })}%`;
}

export function ownershipShareProblem(ownerships: unknown): string | undefined {
  if (!Array.isArray(ownerships) || ownerships.length === 0) return;
  let total = 0;
  let unknown = 0;
  for (const owner of ownerships) {
    const value: unknown = record(owner).sharePercent;
    if (value === null || value === undefined || value === "") {
      unknown++;
      continue;
    }
    const text = typeof value === "string" || typeof value === "number" ? String(value) : "invalid";
    if (!/^\d{1,3}(?:\.\d{1,2})?$/.test(text) || Number(text) <= 0 || Number(text) > 100)
      return "Enter an ownership share greater than 0% and at most 100%, using up to two decimal places, or leave it blank.";
    const [whole, fraction = ""] = text.split(".");
    total += Number(whole) * 100 + Number(fraction.padEnd(2, "0"));
  }
  if (unknown ? total >= 10000 : total !== 10000)
    return unknown
      ? "Known shares must leave a portion for owners whose shares are not recorded."
      : "Ownership shares must total 100% when every share is recorded.";
}
