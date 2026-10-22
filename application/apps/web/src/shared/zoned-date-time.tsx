import { useEffect, useId, useRef, useState } from "react";

export function browserTimeZone() {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
}

export function zonedWallTime(instant: string, timeZone: string) {
  if (!instant) return "";
  try {
    const parts = new Intl.DateTimeFormat("en-CA", {
      timeZone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hourCycle: "h23",
    }).formatToParts(new Date(instant));
    const part = (name: string) => parts.find((item) => item.type === name)?.value;
    return `${part("year")}-${part("month")}-${part("day")}T${part("hour")}:${part("minute")}:${part("second")}`;
  } catch {
    return "";
  }
}

/** Resolve the entered wall clock in its selected zone, never the browser's zone. */
export function zonedInstant(wall: string, timeZone: string, original = "") {
  if (!wall) return "";
  const nominal = Date.parse(`${wall}Z`);
  if (!Number.isFinite(nominal)) throw new Error("Enter a valid date and time.");
  const canonical = new Date(nominal).toISOString().slice(0, 19);
  // Retain the exact original instant in the repeated autumn hour when unchanged.
  if (original && zonedWallTime(original, timeZone) === canonical) return original;
  const candidates = new Set<number>();
  for (const hours of [-36, -12, 0, 12, 36]) {
    const sample = Math.floor(nominal / 1000) * 1000 + hours * 3_600_000;
    const offset =
      Date.parse(`${zonedWallTime(new Date(sample).toISOString(), timeZone)}Z`) - sample;
    const candidate = nominal - offset;
    if (zonedWallTime(new Date(candidate).toISOString(), timeZone) === canonical)
      candidates.add(candidate);
  }
  if (!candidates.size)
    throw new Error("This time does not exist in the selected time zone. Choose another time.");
  // New ambiguous entries use the first occurrence; unchanged entries retain their offset.
  return new Date(Math.min(...candidates)).toISOString();
}

export function TimeZoneSelect({
  value,
  onChange,
  disabled = false,
  label = "Time zone",
  required = false,
}: {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  label?: string;
  required?: boolean;
}) {
  const id = useId();
  const zones = [
    ...new Set([value, browserTimeZone(), "UTC", ...Intl.supportedValuesOf("timeZone")]),
  ];
  return (
    <div>
      <label htmlFor={id}>
        {label}
        {required ? " (required)" : ""}
      </label>
      <select
        id={id}
        name={label}
        required={required}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
      >
        {zones.map((zone) => (
          <option key={zone} value={zone}>
            {zone || "Choose a time zone…"}
          </option>
        ))}
      </select>
    </div>
  );
}

export function ZonedDateTimeInput({
  label,
  value,
  timeZone,
  onChange,
  required = false,
  disabled = false,
}: {
  label: string;
  value: string;
  timeZone: string;
  onChange: (value: string) => void;
  required?: boolean;
  disabled?: boolean;
}) {
  const id = useId();
  const input = useRef<HTMLInputElement>(null);
  const [edit, setEdit] = useState<{ value: string; wall: string; zone: string; error: string }>();
  const current = edit?.value === value && edit.zone === timeZone ? edit : undefined;
  const error = current?.error ?? "";
  useEffect(() => {
    input.current?.setCustomValidity(error);
  }, [error]);
  return (
    <div className="zoned-date-time-field">
      <label htmlFor={id}>
        {label}
        {required ? " (required)" : ""}
      </label>
      <input
        ref={input}
        id={id}
        name={label}
        type="datetime-local"
        step="60"
        required={required}
        disabled={disabled}
        value={current?.wall ?? zonedWallTime(value, timeZone).slice(0, 16)}
        aria-describedby={current?.error ? `${id}-error` : undefined}
        aria-invalid={!!current?.error}
        onChange={(event) => {
          const wall = event.currentTarget.value;
          let next = value,
            error = "";
          try {
            next = zonedInstant(wall, timeZone, value);
          } catch (failure) {
            error = failure instanceof Error ? failure.message : "Enter a valid date and time.";
          }
          event.currentTarget.setCustomValidity(error);
          setEdit({ value: next, wall, zone: timeZone, error });
          if (!error) onChange(next);
        }}
      />
      {current?.error && (
        <small id={`${id}-error`} role="alert">
          {current.error}
        </small>
      )}
    </div>
  );
}
