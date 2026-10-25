import { scalar } from "@epm/contracts/workflows";
import { formatScheduledTime } from "../shared/home-time";

export function MaintenanceAppointment({ item }: { item: Record<string, unknown> }) {
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
              {item[field] ? (
                <time dateTime={scalar(item[field])}>
                  {formatScheduledTime(scalar(item[field]), scalar(item.scheduledTimezone, ""))}
                </time>
              ) : (
                "Not specified"
              )}
            </dd>
          </div>
        ))}
      </dl>
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
