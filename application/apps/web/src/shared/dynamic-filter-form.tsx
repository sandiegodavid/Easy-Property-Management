import { useEffect, useRef, useState, type ComponentPropsWithoutRef } from "react";
import { NavigationType, useLocation, useNavigationType } from "react-router-dom";

type Props = ComponentPropsWithoutRef<"form">;

function filterError(form: HTMLFormElement) {
  const data = new FormData(form);
  for (const [name, value] of data) {
    if (typeof value !== "string" || !value) continue;
    if (
      name.endsWith("Id") &&
      !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value)
    )
      return "Enter a complete record ID to apply this filter.";
    const endName =
      name === "fromOn"
        ? "throughOn"
        : name.endsWith("From")
          ? name.replace(/From$/, "To")
          : name.endsWith("OnOrAfter")
            ? name.replace(/OnOrAfter$/, "OnOrBefore")
            : "";
    const end = endName && data.get(endName);
    if (typeof end === "string" && end && Date.parse(value) > Date.parse(end))
      return "The start date must be on or before the end date.";
  }
  return "";
}

export function DynamicFilterForm({ children, onChange, onSubmit, onReset, ...props }: Props) {
  const location = useLocation();
  const navigationType = useNavigationType();
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const [navigation, setNavigation] = useState({ key: location.key, reset: 0 });
  const [error, setError] = useState("");
  if (navigation.key !== location.key) {
    setNavigation({
      key: location.key,
      reset: navigation.reset + (navigationType === NavigationType.Pop ? 1 : 0),
    });
    if (error) setError("");
  }
  useEffect(() => () => clearTimeout(timer.current), [location.key]);
  return (
    <form
      {...props}
      key={navigation.reset}
      onChange={(event) => {
        onChange?.(event);
        clearTimeout(timer.current);
        const form = event.currentTarget;
        const target = event.target;
        const immediate =
          target instanceof HTMLSelectElement ||
          (target instanceof HTMLInputElement && ["checkbox", "radio"].includes(target.type));
        const apply = () => {
          if (form.isConnected && form.checkValidity()) form.requestSubmit();
        };
        if (immediate) apply();
        else timer.current = setTimeout(apply, 300);
      }}
      onSubmit={(event) => {
        event.preventDefault();
        clearTimeout(timer.current);
        const message = filterError(event.currentTarget);
        setError(message);
        if (message) return;
        onSubmit?.(event);
      }}
      onReset={(event) => {
        clearTimeout(timer.current);
        onReset?.(event);
      }}
    >
      {children}
      {error && <p role="alert">{error}</p>}
    </form>
  );
}
