import { record, scalar } from "@epm/contracts/workflows";
import { formatHomeTime } from "../shared/home-time";
import { label } from "./fields";
import { leasingStatusLabels } from "../shared/leasing-status";
import { formatDate } from "../shared/presentation";

const fieldLabels: Record<string, string> = {
  dueAtUtc: "Due",
  dueTimezone: "Deadline time zone",
  taskDeadlineState: "Deadline",
  followUpAt: "Follow-up",
  followUpTimezone: "Follow-up time zone",
  waitingForLabel: "Waiting for",
  remindAtUtc: "Reminder time",
  acknowledgedAtUtc: "Acknowledged",
  dismissedAtUtc: "Dismissed",
  technicalStatus: "Record status",
  attentionStatus: "Review status",
  attachmentCount: "Attachments",
  receivedAtUtc: "Received",
  occurredAtUtc: "Occurred",
  occurredAtContext: "Reported time context",
  original_name: "Filename",
  media_type: "File type",
  size_bytes: "Size (bytes)",
  storage_state: "Content status",
  verified_at: "Last verified",
  content_sha256: "SHA-256",
  walkthroughOn: "Walkthrough date",
  tenantPresence: "Tenant attendance",
  providerSelectionStatusSnapshot: "Provider selection",
  currentPartyState: "Contact status",
  currentProviderProfileState: "Provider status",
  isAllDay: "All-day task",
  number: "Version",
  revisionNumber: "Version",
  revisionKind: "Change",
  revisionCreatedAt: "Recorded",
  originSystem: "Import origin",
  accountIdentityState: "Account verification",
  submitterKind: "Submitted by",
  preMoveIn: "Move-in inspection",
  postMoveOut: "Move-out inspection",
  ownerDisplayNameSnapshot: "Owner at time of concern",
  propertyDisplayNameSnapshot: "Property at time of concern",
  spaceDisplayNameSnapshot: "Rental unit at time of concern",
  leaseDisplaySnapshot: "Lease at time of concern",
  tenantDisplayNameSnapshot: "Tenant at time of concern",
  raisedAtUtc: "Raised",
  propertyTimezoneSnapshot: "Property time zone",
  availabilityStatus: "Leasing status",
  observedAvailabilityStatus: "Reported leasing status",
  observedOccupancyStatus: "Reported occupancy",
  spaceDisplayName: "Rental unit",
  spaceStatus: "Rental-unit status",
  providerDisplayNameSnapshot: "Provider",
  recordedAssignmentToWorkStartSeconds: "Assignment to recorded work start",
  effectiveKind: "Work entry",
  sourceKind: "Reported by",
  operatorVerified: "Verified by you",
};

// Presentation only: date-only values keep their source calendar day.
export function ReadableFacts({ value, fields }: { value: unknown; fields: string[] }) {
  const values = record(value);
  return (
    <dl className="workflow-facts readable-facts">
      {fields
        .filter((key) => values[key] != null && values[key] !== "" && !/revision/i.test(key))
        .map((key) => {
          const raw = values[key];
          const text = scalar(raw);
          const instant = /(?:AtUtc|At|_at)$/.test(key) && /^\d{4}-\d{2}-\d{2}T/.test(text);
          const enumeration =
            /(?:Status|State|Kind)$/.test(key) ||
            [
              "status",
              "priority",
              "channel",
              "direction",
              "role",
              "kind",
              "type",
              "outcome",
              "disposition",
              "storage_state",
              "failureCode",
              "preMoveIn",
              "postMoveOut",
              "tenantPresence",
              "effectiveKind",
            ].includes(key);
          return (
            <div key={key}>
              <dt>{fieldLabels[key] ?? label(key)}</dt>
              <dd>
                {typeof raw === "boolean"
                  ? raw
                    ? "Yes"
                    : "No"
                  : instant
                    ? formatHomeTime(text)
                    : /availabilityStatus$/i.test(key) && leasingStatusLabels[text]
                      ? leasingStatusLabels[text]
                      : enumeration
                        ? label(text.replaceAll("_", " "))
                        : /(?:On|Date|_on|_date)$/.test(key)
                          ? formatDate(text)
                          : text}
              </dd>
            </div>
          );
        })}
    </dl>
  );
}
