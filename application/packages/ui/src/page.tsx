import type { ReactNode } from "react";

export function Page({ title, children }: { title: string; children: ReactNode }) {
  return (
    <main id="main-content">
      <h1>{title}</h1>
      {children}
    </main>
  );
}
