import { useEffect, useId, useRef, type InputHTMLAttributes, type ReactNode } from "react";

export function TextField({
  id: suppliedId,
  label,
  hint,
  error,
  required = false,
  ...input
}: Omit<InputHTMLAttributes<HTMLInputElement>, "aria-describedby" | "aria-invalid"> & {
  label: string;
  hint?: string;
  error?: string;
}) {
  const generated = useId();
  const id = suppliedId ?? generated;
  return (
    <div className="ui-field">
      <label htmlFor={id}>
        {label} <span>({required ? "required" : "optional"})</span>
      </label>
      {hint && <p id={`${id}-hint`}>{hint}</p>}
      <input
        {...input}
        id={id}
        required={required}
        aria-invalid={error ? true : undefined}
        aria-describedby={
          [hint && `${id}-hint`, error && `${id}-error`].filter(Boolean).join(" ") || undefined
        }
      />
      {error && (
        <p id={`${id}-error`} className="ui-danger">
          {error}
        </p>
      )}
    </div>
  );
}

export function ErrorSummary({
  errors,
}: {
  errors: readonly { fieldId: string; message: string }[];
}) {
  return errors.length ? (
    <div role="alert" className="ui-notice ui-danger">
      <p>
        <strong>Review the following fields</strong>
      </p>
      <ul>
        {errors.map((error) => (
          <li key={error.fieldId}>
            <a
              href={`#${error.fieldId}`}
              onClick={() => document.getElementById(error.fieldId)?.focus()}
            >
              {error.message}
            </a>
          </li>
        ))}
      </ul>
    </div>
  ) : null;
}

/** Caller owns command state. Confirmation invokes once; pending prevents repeat
 * submission and cancellation until the outcome is safe to leave. */
export function ConfirmDialog({
  open,
  title,
  consequence,
  confirmLabel,
  pending = false,
  error,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  consequence: ReactNode;
  confirmLabel: string;
  pending?: boolean;
  error?: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const cancel = useRef<HTMLButtonElement>(null);
  const id = useId();
  useEffect(() => {
    const element = dialog.current;
    if (!element || !open) return;
    const previous = document.activeElement;
    element.showModal();
    cancel.current?.focus();
    return () => {
      element.close();
      if (previous instanceof HTMLElement && previous.isConnected) previous.focus();
    };
  }, [open]);
  return (
    <dialog
      ref={dialog}
      className="ui-dialog"
      aria-labelledby={`${id}-title`}
      aria-describedby={`${id}-impact`}
      onKeyDown={(event) => {
        if (event.key !== "Tab") return;
        const controls = Array.from(
          event.currentTarget.querySelectorAll<HTMLButtonElement>("button:not(:disabled)"),
        );
        const first = controls[0];
        const last = controls.at(-1);
        if (!first || !last) {
          event.preventDefault();
          return;
        }
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }}
      onCancel={(event) => {
        event.preventDefault();
        if (!pending) onCancel();
      }}
    >
      <h2 id={`${id}-title`}>{title}</h2>
      <div id={`${id}-impact`}>{consequence}</div>
      <p role="alert">{error ?? ""}</p>
      <p role="status">{pending ? "Waiting for confirmation…" : ""}</p>
      <div className="ui-actions">
        <button ref={cancel} type="button" disabled={pending} onClick={onCancel}>
          Cancel
        </button>
        <button type="button" disabled={pending} onClick={onConfirm}>
          {confirmLabel}
        </button>
      </div>
    </dialog>
  );
}
