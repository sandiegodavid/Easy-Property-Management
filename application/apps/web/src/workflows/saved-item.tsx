import { useId, type ReactNode } from "react";
import { record, scalar } from "@epm/contracts/workflows";
import { ItemReturnLink, SourceWorkflowLink } from "../shared/home-navigation";
import { formatHomeTime } from "../shared/home-time";
import { OfficialIdList } from "../shared/official-identification";
import { cents } from "./money-presentation";
import { label } from "./fields";
import { formatDate, formatUsd } from "../shared/presentation";

const hidden =
  /(?:^id$|Ids?$|revision|fingerprint|correlation|idempotency|sha256|credential|password|secret|api.?key|token|normalized|^asOf$|^effectiveLocalDate$|^schemaVersion$|^documentNumber$|^lastFour$|^operation|^provenance$|^storage|^location$|^confidence$)/i;
const headings: Record<string, string> = {
  party: "Name and identity",
  profile: "Profile",
  item: "Saved details",
  task: "Task",
  spaces: "Rental units",
  ownerships: "Owners",
  terms: "Rent terms",
  contactMethods: "Contact details",
  areas: "Checklist",
  observations: "Observations",
  category: "Category",
  allocations: "Allocations",
};

function fieldLabel(key: string) {
  const names: Record<string, string> = {
    displayName: "Name",
    displayValue: "Contact",
    isPrimary: "Primary contact",
    partyKind: "Type",
    spaceKind: "Rental type",
    inventoryLayout: "Rental layout",
    sharePercent: "Ownership share",
    ownerKind: "Owner",
    technicalStatus: "Evidence status",
    availableOn: "Open for leasing from",
  };
  return names[key] ?? label(key.replaceAll("_", " "));
}

function text(key: string, value: string | number | boolean) {
  if (key === "sharePercent") return value === "Not recorded" ? value : `${Number(value)}%`;
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (/Minor$/.test(key) && /^-?\d+$/.test(String(value))) return formatUsd(cents(value));
  if (
    /(?:amount|balance|total|principal|refundDue)$/i.test(key) &&
    typeof value === "string" &&
    /^-?\d+\.\d{2}$/.test(value)
  )
    return formatUsd(value);
  if (
    /(?:On|Date|_on|_date)$/.test(key) &&
    typeof value === "string" &&
    /^\d{4}-\d\d-\d\d$/.test(value)
  )
    return formatDate(value);
  if (
    typeof value === "string" &&
    /^\d{4}-\d\d-\d\dT.*(?:Z|[+-]\d\d:\d\d)$/.test(value) &&
    Number.isFinite(Date.parse(value))
  )
    return formatHomeTime(value);
  const words: Record<string, string> = {
    local_operator: "You",
    single_space: "Whole home",
    whole_office: "Whole office",
    office_suites: "Suites",
    available_now: "Open for leasing now",
    available_on: "Open for leasing later",
    unavailable: "Not open for leasing",
  };
  return words[String(value)] ?? String(value).replaceAll("_", " ");
}

/** Render only saved business data, never technical identifiers or unrestricted JSON. */
function SavedData({ value, depth = 0 }: { value: unknown; depth?: number }) {
  if (depth > 5) return null;
  const entries = Object.entries(record(value)).filter(
    ([key, entry]) =>
      !(key === "value" && record(value).displayValue) &&
      !(key === "updatedAt" && record(value).createdAt === entry) &&
      (entry !== null || key === "sharePercent") &&
      entry !== undefined &&
      (key === "officialIds" || !hidden.test(key)) &&
      !(typeof entry === "string" && /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(entry)),
  );
  const facts = entries.filter(
    ([key, entry]) =>
      key === "sharePercent" || ["string", "number", "boolean"].includes(typeof entry),
  );
  return (
    <>
      {!!facts.length && (
        <dl className="saved-item-facts">
          {facts.map(([key, entry]) => (
            <div key={key}>
              <dt>{key.endsWith("Minor") ? fieldLabel(key.slice(0, -5)) : fieldLabel(key)}</dt>
              <dd>{text(key, (entry ?? "Not recorded") as string | number | boolean)}</dd>
            </div>
          ))}
        </dl>
      )}
      {entries
        .filter(([key, entry]) => key !== "sharePercent" && typeof entry === "object")
        .map(([key, entry]) => {
          if (key === "officialIds") {
            const ids = Array.isArray(entry)
              ? entry.map(record).map((id) => ({
                  documentType: scalar(id.documentType),
                  issuingCountry: scalar(id.issuingCountry),
                  lastFour: scalar(id.lastFour),
                  issuingRegion: typeof id.issuingRegion === "string" ? id.issuingRegion : null,
                  expiresOn: typeof id.expiresOn === "string" ? id.expiresOn : null,
                  documentNumber: typeof id.documentNumber === "string" ? id.documentNumber : null,
                }))
              : [];
            return ids.length ? (
              <section key={key}>
                <h3>Official identification</h3>
                <OfficialIdList items={ids} />
              </section>
            ) : null;
          }
          const rows: unknown[] = Array.isArray(entry)
            ? entry.filter((row) => key !== "ownerships" || !record(row).endsOn)
            : [entry];
          return rows.length ? (
            <section
              key={key}
              className="saved-item-section"
              aria-label={headings[key] ?? fieldLabel(key)}
            >
              <h3>{headings[key] ?? fieldLabel(key)}</h3>
              {rows.slice(0, 100).map((row, index) => (
                <div key={index} className="saved-item-entry">
                  {typeof row === "string" ||
                  typeof row === "number" ||
                  typeof row === "boolean" ? (
                    <p>{text(key, row)}</p>
                  ) : (
                    <SavedData value={row} depth={depth + 1} />
                  )}
                </div>
              ))}
              {rows.length > 100 && <p>More details are available on the item page.</p>}
            </section>
          ) : null;
        })}
    </>
  );
}

export function SavedItem({
  title,
  value,
  destination,
  embedded = false,
  children,
}: {
  title: string;
  value?: unknown;
  destination?: { to: string; label: string };
  embedded?: boolean;
  children?: ReactNode;
}) {
  const heading = useId();
  return (
    <section className="saved-item" aria-labelledby={heading} data-embedded={embedded}>
      <header className="saved-item-heading" role="status">
        {embedded ? <h3 id={heading}>{title}</h3> : <h2 id={heading}>{title}</h2>}
      </header>
      {value !== undefined && <SavedData value={value} />}
      {children}
      {destination && (
        <footer className="saved-item-actions">
          {embedded ? (
            <SourceWorkflowLink className="saved-item-return" to={destination.to}>
              {destination.label.replace(/^Back to /, "View ")}
            </SourceWorkflowLink>
          ) : (
            <ItemReturnLink className="saved-item-return" to={destination.to}>
              {destination.label}
            </ItemReturnLink>
          )}
        </footer>
      )}
    </section>
  );
}
