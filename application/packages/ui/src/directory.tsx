import { useId, useRef, type ReactNode } from "react";
import { AsyncRegion, type AsyncState } from "./presentation";

export function DirectoryPage({
  title,
  total,
  state,
  filters,
  sort,
  children,
  nextCursor,
  onContinue,
  continuing = false,
}: {
  title: string;
  total: number | null;
  state: AsyncState;
  filters?: ReactNode;
  sort?: ReactNode;
  children: ReactNode;
  nextCursor: string | null;
  onContinue: (cursor: string) => void;
  continuing?: boolean;
}) {
  return (
    <div className="ui-directory">
      <h2>{title}</h2>
      <p>{total === null ? "Matching total unavailable" : `${total} matching records`}</p>
      <div className="ui-actions">
        {filters}
        {sort}
      </div>
      <AsyncRegion
        title={`${title} results`}
        state={state.kind === "empty" && nextCursor !== null ? { kind: "success" } : state}
      >
        {state.kind === "empty" && nextCursor !== null ? (
          <p>No records on this page. Continue to the next page.</p>
        ) : (
          children
        )}
      </AsyncRegion>
      {nextCursor !== null && (
        <button type="button" disabled={continuing} onClick={() => onContinue(nextCursor)}>
          {continuing ? "Loading next page…" : "Continue results"}
        </button>
      )}
    </div>
  );
}

export interface TableColumn<T> {
  key: string;
  label: string;
  numeric?: boolean;
  value: (row: T) => ReactNode;
}
export function DataTable<T>({
  caption,
  columns,
  rows,
  rowKey,
  rowLabel,
}: {
  caption: string;
  columns: readonly TableColumn<T>[];
  rows: readonly T[];
  rowKey: (row: T) => string;
  rowLabel: (row: T) => string;
}) {
  const id = useId();
  const scroll = useRef<HTMLDivElement>(null);
  return (
    <div role="region" aria-labelledby={id}>
      <div className="ui-actions">
        <button
          type="button"
          aria-label={`Scroll ${caption} left`}
          onClick={() => scroll.current?.scrollBy({ left: -200 })}
        >
          ←
        </button>
        <button
          type="button"
          aria-label={`Scroll ${caption} right`}
          onClick={() => scroll.current?.scrollBy({ left: 200 })}
        >
          →
        </button>
      </div>
      <div className="ui-table-scroll" ref={scroll}>
        <table className="ui-table">
          <caption id={id}>{caption}</caption>
          <thead>
            <tr>
              <th scope="col">Record</th>
              {columns.map((column) => (
                <th
                  key={column.key}
                  scope="col"
                  className={column.numeric ? "ui-numeric" : undefined}
                >
                  {column.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={rowKey(row)}>
                <th scope="row">{rowLabel(row)}</th>
                {columns.map((column) => (
                  <td key={column.key} className={column.numeric ? "ui-numeric" : undefined}>
                    {column.value(row) ?? "Unavailable"}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
