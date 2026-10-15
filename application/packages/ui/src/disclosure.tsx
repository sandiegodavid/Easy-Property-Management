import { useId, useLayoutEffect, useRef, useState, type ReactNode } from "react";

export function DisclosureList({
  children,
  showHint = true,
}: {
  children: ReactNode;
  showHint?: boolean;
}) {
  return (
    <div className="ui-disclosures">
      {showHint && (
        <p>Click anywhere on an item’s summary bar to expand or collapse its details.</p>
      )}
      {children}
    </div>
  );
}

/** Keep source identity in the parent's React key. Children receive visibility so
 * feature-owned detail fetching/polling can pause while a retained panel is hidden. */
export function DisclosureRow({
  title,
  summary,
  status,
  actionLabel,
  open,
  onOpenChange,
  children,
}: {
  title: string;
  summary?: string;
  status?: string;
  actionLabel?: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  children: (visible: boolean) => ReactNode;
}) {
  const id = useId();
  const button = useRef<HTMLButtonElement>(null);
  const focusInside = useRef(false);
  const [mounted, setMounted] = useState(open);
  const [tooltipDismissed, setTooltipDismissed] = useState(false);
  useLayoutEffect(() => {
    if (!open && focusInside.current) {
      button.current?.focus();
      focusInside.current = false;
    }
  }, [open]);
  // Record the first opening without unmounting previously edited children.
  if (open && !mounted) setMounted(true);
  return (
    <div className={`ui-disclosure${actionLabel ? " ui-disclosure--action" : ""}`}>
      <div className="ui-summary-bar" data-tooltip-dismissed={tooltipDismissed}>
        <button
          ref={button}
          id={`${id}-summary`}
          className="ui-summary"
          type="button"
          aria-expanded={open}
          aria-controls={`${id}-panel`}
          aria-describedby={actionLabel ? `${id}-action` : undefined}
          onMouseEnter={() => setTooltipDismissed(false)}
          onFocus={() => setTooltipDismissed(false)}
          onKeyDown={(event) => {
            if (event.key === "Escape") setTooltipDismissed(true);
          }}
          onClick={() => onOpenChange(!open)}
        >
          <span>
            <strong>{title}</strong>
            {summary && <span className="ui-summary-text">{summary}</span>}
          </span>
          {status && <span>{status}</span>}
          {actionLabel && <span className="ui-summary-action">{actionLabel}</span>}
          <span className="ui-chevron" aria-hidden="true">
            ⌄
          </span>
        </button>
        {actionLabel && (
          <span id={`${id}-action`} role="tooltip" className="ui-summary-tooltip">
            {actionLabel}
          </span>
        )}
      </div>
      <div
        id={`${id}-panel`}
        role="region"
        aria-labelledby={`${id}-summary`}
        hidden={!open}
        onFocusCapture={() => {
          focusInside.current = true;
        }}
        onBlurCapture={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget) && !event.currentTarget.hidden)
            focusInside.current = false;
        }}
      >
        {mounted && children(open)}
        {mounted && (
          <button
            type="button"
            onClick={() => {
              onOpenChange(false);
              button.current?.focus();
            }}
          >
            Collapse details
          </button>
        )}
      </div>
    </div>
  );
}
