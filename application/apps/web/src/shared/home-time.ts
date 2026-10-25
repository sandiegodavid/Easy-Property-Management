import { formatDate } from "./presentation";

// System activity uses browser time. Schedules use their saved source zone;
// calendar dates are never shifted as instants.
function formatTime(instant: string, timeZone?: string | null) {
  const formatter = new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
    ...(timeZone ? { timeZone } : {}),
  });
  return `${formatter.format(new Date(instant))} · ${formatter.resolvedOptions().timeZone}`;
}

export function formatHomeTime(instant: string) {
  return formatTime(instant);
}

export function formatScheduledTime(instant: string, timeZone?: string | null) {
  return formatTime(instant, timeZone);
}

export function formatRecordInstant(
  instant: string,
  field: string,
  record: Record<string, unknown>,
) {
  const zoneField: Record<string, string> = {
    startsAtUtc: "scheduledTimezone",
    endsAtUtc: "scheduledTimezone",
    dueAtUtc: "dueTimezone",
    followUpAt: "followUpTimezone",
    followUpAtUtc: "followUpTimezone",
    remindAtUtc: "dueTimezone",
  };
  const zone = zoneField[field] ? record[zoneField[field]] : undefined;
  return formatTime(instant, typeof zone === "string" ? zone : undefined);
}

type TemporalFact = {
  at?: string | null;
  on?: string | null;
  timeZone?: string | null;
};

function formatTemporal(fact: TemporalFact, includeSourceTime: boolean) {
  if (fact.on) return `${formatDate(fact.on)} · All day · ${fact.timeZone}`;
  if (!fact.at) return "";
  const local = formatHomeTime(fact.at);
  const operatorZone = new Intl.DateTimeFormat().resolvedOptions().timeZone;
  return fact.timeZone && fact.timeZone !== operatorZone
    ? includeSourceTime
      ? `${local} · Source time: ${formatScheduledTime(fact.at, fact.timeZone)}`
      : `${local} · Source time zone: ${fact.timeZone}`
    : local;
}

export function formatHomeTemporal(fact: TemporalFact) {
  return formatTemporal(fact, false);
}

export function formatHomeSchedule(fact: TemporalFact) {
  return formatTemporal(fact, true);
}
