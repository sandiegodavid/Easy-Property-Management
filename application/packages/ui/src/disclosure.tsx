import { useId, useLayoutEffect, useRef, useState, type ReactNode } from "react";

export function DisclosureList({ children }: { children: ReactNode }) {
  return (
    <div className="ui-disclosures">
      <p>Click anywhere on an item’s summary bar to expand or collapse its details.</p>
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
  open,
  onOpenChange,
  children,
}: {
  title: string;
  summary?: string;
  status?: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  children: (visible: boolean) => ReactNode;
}) {
  const id = useId();
  const button = useRef<HTMLButtonElement>(null);
  const focusInside = useRef(false);
  const [mounted, setMounted] = useState(open);
  useLayoutEffect(() => {
    if (!open && focusInside.current) {
      button.current?.focus();
      focusInside.current = false;
    }
  }, [open]);
  // Record the first opening without unmounting previously edited children.
  if (open && !mounted) setMounted(true);
  return (
    <div className="ui-disclosure">
      <button
        ref={button}
        id={`${id}-summary`}
        className="ui-summary"
        type="button"
        aria-expanded={open}
        aria-controls={`${id}-panel`}
        onClick={() => onOpenChange(!open)}
      >
        <span>
          <strong>{title}</strong>
          {summary && <span className="ui-summary-text">{summary}</span>}
        </span>
        {status && <span>{status}</span>}
        <span className="ui-chevron" aria-hidden="true">
          ⌄
        </span>
      </button>
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
