import type { ReactNode } from "react";

export function Page({
  title,
  brand,
  children,
}: {
  title: string;
  brand?: ReactNode;
  children: ReactNode;
}) {
  return (
    <main id="main-content">
      <h1 className="ui-brand">
        {brand && <span aria-hidden="true">{brand}</span>}
        <span className={brand ? "ui-sr-only" : undefined}>{title}</span>
      </h1>
      {children}
    </main>
  );
}
