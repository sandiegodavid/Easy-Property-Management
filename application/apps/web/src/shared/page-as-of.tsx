import { createContext, useContext, useEffect, useId, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { formatHomeTime } from "./home-time";

type Capture = { asOf: string; priority: number };
type Register = (id: string, capture: Capture) => () => void;
const PageCapture = createContext<Register | null>(null);

export function PageAsOfProvider({ children }: { children: ReactNode }) {
  const [captures, setCaptures] = useState<Record<string, Capture>>({});
  const register = useMemo<Register>(
    () => (id, capture) => {
      setCaptures((current) => ({ ...current, [id]: capture }));
      return () => {
        setCaptures((current) => {
          const next = { ...current };
          delete next[id];
          return next;
        });
      };
    },
    [],
  );
  // Prefer the page's capture; independent sections fall back to the oldest capture.
  const capture = Object.values(captures).sort(
    (a, b) => a.priority - b.priority || Date.parse(a.asOf) - Date.parse(b.asOf),
  )[0];
  return (
    <PageCapture.Provider value={register}>
      {capture && (
        <p className="page-as-of">
          As of <time dateTime={capture.asOf}>{formatHomeTime(capture.asOf)}</time>
        </p>
      )}
      {children}
    </PageCapture.Provider>
  );
}

export function PageAsOf({ asOf, priority = 0 }: { asOf: string; priority?: number }) {
  const register = useContext(PageCapture);
  const id = useId();
  useEffect(() => register?.(id, { asOf, priority }), [register, id, asOf, priority]);
  return null;
}
