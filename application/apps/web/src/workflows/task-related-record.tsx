import { useEffect, useId, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@epm/contracts";
import { scalar } from "@epm/contracts/workflows";
import { useWorkspace } from "../app/workspace-gate";
import { readResult } from "./reads";

const groups = {
  properties: "Property",
  spaces: "Rental unit",
  owners: "Owner",
  tenants: "Tenant",
  leases: "Lease",
  maintenance: "Maintenance issue",
} as const;

export function TaskRelatedRecord({
  value,
  onChange,
  disabled,
}: {
  value: Record<string, unknown>;
  onChange: (value: Record<string, unknown>) => void;
  disabled: boolean;
}) {
  const { scope } = useWorkspace();
  const id = useId();
  const [group, setGroup] = useState<keyof typeof groups>("properties");
  const [input, setInput] = useState("");
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState<string>();
  useEffect(() => {
    const timer = setTimeout(() => setQuery(input.trim()), 250);
    return () => clearTimeout(timer);
  }, [input]);
  const results = useQuery({
    queryKey: scope.key("task-related-record", group, query, cursor),
    enabled: query.length >= 2 && query === input.trim(),
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/operator/search", {
          signal,
          params: { query: { q: query, group, limit: 10, includeArchived: false, cursor } },
        }),
      ),
  });
  const page = query === input.trim() ? results.data?.groups[group] : undefined;
  return (
    <fieldset>
      <legend>Related record (optional)</legend>
      {!!value.relatedEntityId && (
        <p>
          Related to: <strong>{scalar(value.relatedLabel, "Selected record")}</strong>{" "}
          <button
            type="button"
            disabled={disabled}
            onClick={() =>
              onChange({
                ...value,
                relatedEntityType: undefined,
                relatedEntityId: undefined,
                relatedLabel: undefined,
              })
            }
          >
            Remove related record
          </button>
        </p>
      )}
      <div>
        <label htmlFor={`${id}-type`}>Record type</label>
        <select
          id={`${id}-type`}
          name="relatedRecordType"
          value={group}
          disabled={disabled}
          onChange={(event) => {
            setGroup(event.target.value as keyof typeof groups);
            setCursor(undefined);
          }}
        >
          {Object.entries(groups).map(([key, title]) => (
            <option key={key} value={key}>
              {title}
            </option>
          ))}
        </select>
      </div>
      <label>
        Find a related record
        <input
          type="search"
          value={input}
          disabled={disabled}
          maxLength={200}
          placeholder="Enter at least two characters"
          onChange={(event) => {
            setInput(event.target.value);
            setCursor(undefined);
          }}
        />
      </label>
      {results.isFetching && <p role="status">Finding records…</p>}
      {results.error && <p role="alert">Related records are unavailable. Try again.</p>}
      {page && page.items === null && (
        <p role="alert">Related records are unavailable. Try again.</p>
      )}
      {page?.items && (
        <>
          {!page.items.length && <p>No matching records.</p>}
          <ul>
            {page.items.map((hit) => (
              <li key={hit.sourceId}>
                <button
                  type="button"
                  disabled={disabled}
                  onClick={() => {
                    onChange({
                      ...value,
                      relatedEntityType: ["owner", "tenant"].includes(hit.target.entityType)
                        ? "party"
                        : hit.target.entityType,
                      relatedEntityId: hit.target.entityId,
                      relatedLabel: hit.label,
                    });
                    setInput("");
                    setCursor(undefined);
                  }}
                >
                  Use {hit.label}
                </button>
                <p>{hit.context}</p>
              </li>
            ))}
          </ul>
          {page.nextCursor && (
            <button
              type="button"
              disabled={disabled || results.isFetching}
              onClick={() => setCursor(page.nextCursor ?? undefined)}
            >
              More matching records
            </button>
          )}
          {cursor && (
            <button type="button" disabled={disabled} onClick={() => setCursor(undefined)}>
              First matching records
            </button>
          )}
        </>
      )}
    </fieldset>
  );
}
