import type { ReactNode } from "react";

export function EvidenceItem({
  name,
  state,
  children,
}: {
  name: string;
  state?: string;
  children: ReactNode;
}) {
  return (
    <div className="evidence-item">
      <div className="evidence-item-heading">
        <strong>{name}</strong>
        {state && (
          <span className="evidence-item-state">
            {state.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase())}
          </span>
        )}
      </div>
      <div className="evidence-item-actions">{children}</div>
    </div>
  );
}
