/** Calendar dates stay in the source calendar, never the browser's UTC offset. */
export function formatDate(value: string): string {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeZone: "UTC" }).format(
    new Date(`${value}T12:00:00Z`),
  );
}

/** Format decimal USD without floating-point rounding or loss of large integer precision. */
export function formatUsd(value: string | number): string {
  const [whole, fraction = "00"] = String(value).split(".");
  return `USD ${whole.startsWith("-") ? "-" : ""}${BigInt(whole.replace(/^-/, "")).toLocaleString("en-US")}.${fraction.padEnd(2, "0")}`;
}

export function formStatus(draft: string, command: string): string {
  if (command === "outcome_unknown") return "Submission needs checking";
  if (command === "submitting") return "Saving your changes…";
  if (command === "committed") return "Changes saved";
  if (draft === "failed") return "Your form could not be saved. Try saving it again.";
  if (draft === "conflicted") return "Your form changed elsewhere. Review the latest saved copy.";
  if (draft === "dirty") return "Unsaved changes";
  if (draft === "saving") return "Saving unfinished form…";
  return "Unfinished form saved";
}
