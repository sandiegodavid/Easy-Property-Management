import { record, scalar } from "@epm/contracts/workflows";
import { officialIdLabels } from "../shared/official-identification";

export function OfficialIdFields({
  value,
  onChange,
  disabled,
  documentTypes,
  allowsFullNumber,
}: {
  value: unknown;
  onChange: (value: unknown) => void;
  disabled: boolean;
  documentTypes: (string | number)[];
  allowsFullNumber: boolean;
}) {
  const items: unknown[] = Array.isArray(value) ? value : [];
  return (
    <fieldset disabled={disabled}>
      <legend>Official IDs</legend>
      <p>
        {allowsFullNumber
          ? "An optional full ID number can be saved for reference and is hidden by default. Full numbers remain in workspace history and backups, but are hidden from general activity. Do not upload document scans."
          : "Only masked details are saved. Do not enter full document numbers or upload scans."}
      </p>
      {items.map((value, index) => {
        const item = record(value);
        const updateFields = (patch: Record<string, unknown>) =>
          onChange(
            items.map((old, position) => (position === index ? { ...item, ...patch } : old)),
          );
        const update = (key: string, next: string | null) => updateFields({ [key]: next });
        return (
          <fieldset key={index}>
            <legend>Official ID {index + 1}</legend>
            <label>
              ID type (required)
              <select
                value={scalar(item.documentType, "")}
                onChange={(event) => update("documentType", event.target.value)}
              >
                <option value="">Choose…</option>
                {documentTypes.map((type) => (
                  <option key={type} value={type}>
                    {officialIdLabels[String(type)] ?? type}
                  </option>
                ))}
              </select>
            </label>
            {allowsFullNumber && (
              <label>
                Full ID number (optional)
                <input
                  type="password"
                  value={scalar(item.documentNumber, "")}
                  maxLength={80}
                  autoComplete="off"
                  onChange={(event) => {
                    const number = event.target.value;
                    updateFields({
                      documentNumber: number || null,
                      ...(number
                        ? { lastFour: number.replace(/[^A-Za-z0-9]/g, "").slice(-4) }
                        : {}),
                    });
                  }}
                />
                <small>
                  Enter only if needed for your records. Its last four characters are filled below.
                </small>
              </label>
            )}
            <label>
              Issuing country (two-letter code) (required)
              <input
                value={scalar(item.issuingCountry, "")}
                maxLength={2}
                onChange={(event) => update("issuingCountry", event.target.value.toUpperCase())}
              />
            </label>
            <label>
              Issuing state or region (optional)
              <input
                value={scalar(item.issuingRegion, "")}
                maxLength={10}
                onChange={(event) =>
                  update("issuingRegion", event.target.value.toUpperCase() || null)
                }
              />
            </label>
            <label>
              Last four letters or digits only (required)
              <input
                value={scalar(item.lastFour, "")}
                maxLength={4}
                readOnly={!!item.documentNumber}
                autoComplete="off"
                onChange={(event) => update("lastFour", event.target.value)}
              />
            </label>
            <label>
              Expiration date (optional)
              <input
                type="date"
                value={scalar(item.expiresOn, "")}
                onChange={(event) => update("expiresOn", event.target.value || null)}
              />
            </label>
            <button
              type="button"
              onClick={() => onChange(items.filter((_, position) => position !== index))}
            >
              Remove official ID {index + 1}
            </button>
          </fieldset>
        );
      })}
      <button type="button" disabled={items.length >= 10} onClick={() => onChange([...items, {}])}>
        Add official ID
      </button>
    </fieldset>
  );
}
