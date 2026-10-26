import { createRoot } from "react-dom/client";
import { formatHomeSchedule, formatHomeTime, formatScheduledTime } from "../src/shared/home-time";
import { MaintenanceAppointment } from "../src/workflows/maintenance-appointment";
import { ReadableFacts } from "../src/workflows/readable-facts";
import { SavedItem } from "../src/workflows/saved-item";

const instant = new URLSearchParams(location.search).get("at") ?? "2026-07-02T17:00:00Z";
const zones = ["America/Los_Angeles", "America/Chicago", "America/New_York"];

createRoot(document.getElementById("root")!).render(
  <>
    <p data-testid="system-time">{formatHomeTime(instant)}</p>
    <p data-testid="unlinked-time">{formatScheduledTime(instant)}</p>
    {zones.map((zone) => (
      <section key={zone} aria-label={zone}>
        <MaintenanceAppointment
          item={{ purpose: "Visit", startsAtUtc: instant, scheduledTimezone: zone }}
        />
        <ReadableFacts
          value={{
            dueAtUtc: instant,
            dueTimezone: zone,
            followUpAt: instant,
            followUpTimezone: zone,
            createdAt: instant,
          }}
          fields={["dueAtUtc", "followUpAt", "createdAt"]}
        />
        <SavedItem
          title="Appointment saved"
          value={{ startsAtUtc: instant, scheduledTimezone: zone, createdAt: instant }}
        />
        <SavedItem
          title="Reminder saved"
          displayTimeZone={zone}
          value={{
            dueTimezone: "Asia/Tokyo",
            reminders: [{ remindAtUtc: instant, createdAt: instant }],
          }}
        />
        <p data-testid="home-time">{formatHomeSchedule({ at: instant, timeZone: zone })}</p>
        <p data-testid="all-day">{formatHomeSchedule({ on: "2026-07-02", timeZone: zone })}</p>
      </section>
    ))}
  </>,
);
