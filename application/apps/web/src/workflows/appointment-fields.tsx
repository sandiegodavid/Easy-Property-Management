import { record, scalar, type RequestSchema } from "@epm/contracts/workflows";
import { TimeZoneSelect, ZonedDateTimeInput } from "../shared/zoned-date-time";
import { useDefaultTimeZone } from "../shared/form-time-zone";
import { Fields } from "./fields";

export function AppointmentFields({
  schema,
  value,
  onChange,
  disabled,
}: {
  schema: RequestSchema;
  value: Record<string, unknown>;
  onChange: (value: unknown) => void;
  disabled: boolean;
}) {
  const defaultZone = useDefaultTimeZone();
  const zone = scalar(value.scheduledTimezone) || defaultZone;
  return (
    <div className="tidy-form-sections">
      <section className="tidy-form-section" aria-label="Appointment schedule">
        <h3>Appointment schedule</h3>
        <div className="tidy-form-grid">
          <ZonedDateTimeInput
            label="Starts at"
            required
            value={scalar(value.startsAtUtc)}
            timeZone={zone}
            disabled={disabled}
            onChange={(next) => onChange({ ...value, startsAtUtc: next, scheduledTimezone: zone })}
          />
          <ZonedDateTimeInput
            label="Ends at"
            value={scalar(value.endsAtUtc)}
            timeZone={zone}
            disabled={disabled}
            onChange={(next) =>
              onChange({ ...value, endsAtUtc: next || null, scheduledTimezone: zone })
            }
          />
          <TimeZoneSelect
            value={zone}
            disabled={disabled}
            onChange={(next) => onChange({ ...value, scheduledTimezone: next })}
          />
        </div>
        <p className="record-detail-note">
          Choose a date and time or type them directly. Leave the end blank if it is not yet known.
          Changing the time zone displays the same appointment in that zone.
        </p>
      </section>
      <section className="tidy-form-section" aria-label="Appointment details">
        <h3>Appointment details</h3>
        <Fields
          schema={{
            ...schema,
            properties: Object.fromEntries(
              Object.entries(schema.properties ?? {}).filter(
                ([key]) => !["startsAtUtc", "endsAtUtc", "scheduledTimezone"].includes(key),
              ),
            ),
          }}
          value={value}
          disabled={disabled}
          showChangeControls={false}
          onChange={(next) => onChange(record(next))}
        />
      </section>
    </div>
  );
}
