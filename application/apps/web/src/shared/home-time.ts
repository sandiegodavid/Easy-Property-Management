// Instants are displayed in the operator's browser time zone. Calendar dates
// remain in their owning source's zone and must never be shifted as instants.
export function formatHomeTime(instant: string) {
  const formatter = new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
  return `${formatter.format(new Date(instant))} · ${formatter.resolvedOptions().timeZone}`;
}

export function formatHomeTemporal(fact: {
  at?: string | null;
  on?: string | null;
  timeZone?: string | null;
}) {
  if (fact.on) return `${fact.on} · All day · ${fact.timeZone}`;
  if (!fact.at) return "";
  const local = formatHomeTime(fact.at);
  const operatorZone = new Intl.DateTimeFormat().resolvedOptions().timeZone;
  return fact.timeZone && fact.timeZone !== operatorZone
    ? `${local} · Source time zone: ${fact.timeZone}`
    : local;
}
