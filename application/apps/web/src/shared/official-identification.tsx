import { useState } from "react";

export const officialIdLabels: Record<string, string> = {
  license: "License",
  passport: "Passport",
  drivers_license: "Driver’s license",
  state_id: "State ID",
  national_id: "National ID",
  business_registration: "Business registration",
};

export function OfficialIdList({
  items,
}: {
  items: {
    documentType: string;
    issuingCountry: string;
    lastFour: string;
    issuingRegion?: string | null;
    expiresOn?: string | null;
    documentNumber?: string | null;
  }[];
}) {
  return (
    <ul className="record-list">
      {items.map((item, index) => (
        <li key={index}>
          <strong>{officialIdLabels[item.documentType] ?? item.documentType}</strong>
          <span>
            {" "}
            · {item.issuingCountry}
            {item.issuingRegion ? ` / ${item.issuingRegion}` : ""} · Ending in {item.lastFour}
          </span>
          {item.expiresOn && <span> · Expires {item.expiresOn}</span>}
          {item.documentNumber && (
            <IdNumber key={item.documentNumber} number={item.documentNumber} />
          )}
        </li>
      ))}
    </ul>
  );
}
function IdNumber({ number }: { number: string }) {
  const [shown, setShown] = useState(false);
  return (
    <div>
      <button type="button" aria-expanded={shown} onClick={() => setShown(!shown)}>
        {shown ? "Hide ID number" : "Show ID number"}
      </button>
      {shown && <span> {number}</span>}
    </div>
  );
}
