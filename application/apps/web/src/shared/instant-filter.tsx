import { useId } from "react";

function localValue(value: string) {
  if (!value) return "";
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return "";
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, -1);
}

/** Display browser-local dates while keeping API filters as exact zoned instants. */
export function InstantFilter({
  name,
  label,
  value,
}: {
  name: string;
  label: string;
  value: string;
}) {
  const id = useId();
  return (
    <div>
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        name={name}
        type="datetime-local"
        step="any"
        defaultValue={localValue(value)}
        data-filter-instant
        data-original-instant={value}
        aria-describedby={`${id}-zone`}
        onChange={(event) => {
          const input = event.currentTarget;
          const date = new Date(input.value);
          input.setCustomValidity(
            input.value &&
              (!Number.isFinite(date.getTime()) ||
                localValue(date.toISOString()) !==
                  new Date(`${input.value}Z`).toISOString().slice(0, -1))
              ? "Choose a time that exists in your time zone."
              : "",
          );
        }}
      />
      <small id={`${id}-zone`}>
        Your time zone: {Intl.DateTimeFormat().resolvedOptions().timeZone}
      </small>
    </div>
  );
}

export function filterFormData(form: HTMLFormElement) {
  const data = new FormData(form);
  for (const input of form.querySelectorAll<HTMLInputElement>("input[data-filter-instant]")) {
    if (input.value) {
      const original = input.dataset.originalInstant;
      const unchanged =
        original &&
        new Date(`${input.value}Z`).getTime() === new Date(`${localValue(original)}Z`).getTime();
      data.set(input.name, unchanged ? original : new Date(input.value).toISOString());
    }
  }
  return data;
}
