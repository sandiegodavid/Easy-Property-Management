import { useId, useState } from "react";

export function DisclosureHelp() {
  const id = useId();
  const [dismissed, setDismissed] = useState(false);
  return (
    <div className="home-disclosure-help" data-dismissed={dismissed}>
      <button
        type="button"
        aria-label="How to expand items"
        aria-describedby={id}
        onMouseEnter={() => setDismissed(false)}
        onFocus={() => setDismissed(false)}
        onClick={() => setDismissed(false)}
        onKeyDown={(event) => {
          if (event.key === "Escape") setDismissed(true);
        }}
      >
        <span aria-hidden="true">ⓘ</span>
      </button>
      <p id={id} role="tooltip">
        Click anywhere on an item’s summary bar to expand or collapse its details.
      </p>
    </div>
  );
}
