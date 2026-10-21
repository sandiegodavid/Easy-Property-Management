import { scalar } from "@epm/contracts/workflows";
import { formatHomeTime } from "../shared/home-time";

export function MaintenanceAppointment({ item }: { item: Record<string, unknown> }) {
  const operatorZone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  return (
    <div className="maintenance-appointment">
      <header>
        <h3>{scalar(item.purpose, "Appointment")}</h3>
        <span className="maintenance-record-status">
          {scalar(item.status).replaceAll("_", " ")}
        </span>
      </header>
      <dl className="maintenance-appointment-times">
        {[
          ["Starts", "startsAtUtc"],
          ["Ends", "endsAtUtc"],
        ].map(([title, field]) => (
          <div key={field}>
            <dt>{title}</dt>
            <dd>
              <time dateTime={scalar(item[field])}>{formatHomeTime(scalar(item[field]))}</time>
            </dd>
          </div>
        ))}
      </dl>
      {item.scheduledTimezone !== operatorZone && (
        <p className="ui-muted">Scheduled time zone: {scalar(item.scheduledTimezone)}</p>
      )}
      {!!item.instructions && (
        <p>
          <strong>Instructions:</strong> {scalar(item.instructions)}
        </p>
      )}
      {!!item.outcomeNote && (
        <p>
          <strong>Outcome:</strong> {scalar(item.outcomeNote)}
        </p>
      )}
      {!!item.cancellationReason && (
        <p>
          <strong>Cancellation reason:</strong> {scalar(item.cancellationReason)}
        </p>
      )}
    </div>
  );
}
