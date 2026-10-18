import { record, scalar } from "@epm/contracts/workflows";

export function OwnerContactFields({
  value,
  onChange,
  disabled,
}: {
  value: unknown;
  onChange: (contacts: Record<string, unknown>[]) => void;
  disabled: boolean;
}) {
  const contacts = Array.isArray(value) ? value.map(record) : [];
  const address = contacts.find((contact) => contact.methodKind === "mailing_address");
  return (
    <fieldset className="owner-contact-fields">
      <legend>Contact details (optional)</legend>
      <p className="property-edit-hint">
        These details belong to the person or organization and are shared wherever they appear in
        the app.
      </p>
      {contacts.map(
        (contact, index) =>
          contact.methodKind !== "mailing_address" && (
            <div key={index} className="owner-contact-entry">
              <label>
                {contact.methodKind === "email" ? "Email" : "Phone number"}
                <input
                  type={contact.methodKind === "email" ? "email" : "tel"}
                  required
                  disabled={disabled}
                  maxLength={320}
                  value={scalar(contact.value, "")}
                  onChange={(event) =>
                    onChange(
                      contacts.map((item, position) =>
                        position === index ? { ...item, value: event.target.value } : item,
                      ),
                    )
                  }
                />
              </label>
              <label>
                Label (optional)
                <input
                  disabled={disabled}
                  maxLength={80}
                  placeholder={contact.methodKind === "email" ? "e.g. Personal" : "e.g. Mobile"}
                  value={scalar(contact.label, "")}
                  onChange={(event) =>
                    onChange(
                      contacts.map((item, position) =>
                        position === index
                          ? { ...item, label: event.target.value || undefined }
                          : item,
                      ),
                    )
                  }
                />
              </label>
              <button
                type="button"
                disabled={disabled}
                aria-label={`Remove ${contact.methodKind === "email" ? "email" : "phone number"} ${index + 1}`}
                onClick={() => onChange(contacts.filter((_, position) => position !== index))}
              >
                Remove
              </button>
            </div>
          ),
      )}
      <div className="owner-contact-add-actions">
        <button
          type="button"
          disabled={disabled || contacts.length >= 99}
          onClick={() => onChange([...contacts, { methodKind: "email", value: "" }])}
        >
          Add email
        </button>
        <button
          type="button"
          disabled={disabled || contacts.length >= 99}
          onClick={() => onChange([...contacts, { methodKind: "phone", value: "" }])}
        >
          Add phone number
        </button>
      </div>
      <label>
        Mailing address
        <textarea
          disabled={disabled}
          maxLength={1000}
          rows={3}
          placeholder="Street address, city, region, postal code and country"
          value={scalar(address?.value, "")}
          onChange={(event) =>
            onChange([
              ...contacts.filter((contact) => contact.methodKind !== "mailing_address"),
              ...(event.target.value.trim()
                ? [{ methodKind: "mailing_address", value: event.target.value }]
                : []),
            ])
          }
        />
      </label>
    </fieldset>
  );
}
