import { useId, type ReactNode } from "react";

export function InlineNotice({
  children,
  tone = "info",
}: {
  children: ReactNode;
  tone?: "info" | "success" | "warning" | "danger";
}) {
  return <div className={`ui-notice ui-${tone}`}>{children}</div>;
}
export function EmptyState({
  title,
  children,
  action,
}: {
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="ui-empty">
      <p>
        <strong>{title}</strong>
      </p>
      {children}
      {action}
    </div>
  );
}
export function Toast({ message }: { message: string }) {
  return (
    <div className="ui-toast" role="status" aria-atomic="true">
      {message}
    </div>
  );
}
export type AsyncState =
  | { kind: "loading"; message: string }
  | { kind: "empty"; message: string }
  | { kind: "unavailable" | "error"; message: string; recovery?: ReactNode }
  | { kind: "success"; asOf?: string }
  | { kind: "refreshing" | "partial"; message: string; asOf: string }
  | { kind: "stale"; message: string; asOf: string; recovery?: ReactNode };

/** Availability and timestamps come from the source. Retained data is shown only
 * when the caller explicitly chooses stale/refreshing/partial. */
export function AsyncRegion({
  title,
  state,
  children,
  formatTimestamp,
  showCaptureTime = true,
  footer,
  headingAction,
  showHeading = true,
}: {
  title: string;
  state: AsyncState;
  children?: ReactNode;
  formatTimestamp?: (instant: string) => string;
  showCaptureTime?: boolean;
  footer?: ReactNode;
  headingAction?: ReactNode;
  showHeading?: boolean;
}) {
  const id = useId();
  const content = ["success", "refreshing", "stale", "partial"].includes(state.kind);
  return (
    <section
      className="ui-region"
      aria-labelledby={showHeading ? id : undefined}
      aria-label={showHeading ? undefined : title}
    >
      {!showHeading ? null : headingAction ? (
        <div className="ui-region-heading">
          <h3 id={id}>{title}</h3>
          {headingAction}
        </div>
      ) : (
        <h3 id={id}>{title}</h3>
      )}
      <div role="status" aria-atomic="true">
        {state.kind === "success" ? "" : state.message}
      </div>
      {showCaptureTime && "asOf" in state && state.asOf && (
        <p className="ui-muted">
          As of{" "}
          <time dateTime={state.asOf}>
            {formatTimestamp ? formatTimestamp(state.asOf) : state.asOf}
          </time>
        </p>
      )}
      <div aria-busy={state.kind === "loading" || state.kind === "refreshing"}>
        {state.kind === "empty" && <EmptyState title="No matching records" />}
        {content && children}
      </div>
      {"recovery" in state && state.recovery}
      {footer && <footer className="ui-region-footer">{footer}</footer>}
    </section>
  );
}

export type DraftState =
  | { kind: "dirty" | "saving" | "failed" | "conflicted" }
  | { kind: "saved"; acknowledgedAt: string };
export function DraftStatus({ state }: { state: DraftState }) {
  const labels = {
    dirty: "Unsaved changes",
    saving: "Saving…",
    failed: "Save failed",
    conflicted: "Conflicting changes — review required",
  };
  return (
    <p role="status">
      {state.kind === "saved" ? (
        <>
          Draft saved <time dateTime={state.acknowledgedAt}>{state.acknowledgedAt}</time>
        </>
      ) : (
        labels[state.kind]
      )}
    </p>
  );
}

export function HistoryLink({ href, label = "View history" }: { href: string; label?: string }) {
  return <a href={href}>{label}</a>;
}
