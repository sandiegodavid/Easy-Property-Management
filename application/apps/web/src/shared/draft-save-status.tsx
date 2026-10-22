import { formStatus } from "./presentation";
import { formatHomeTime } from "./home-time";

export function draftSaveLabel(draft: string) {
  if (draft === "saved") return "Saved";
  if (draft === "saving") return "Saving unfinished form…";
  if (draft === "failed") return "Retry saving unfinished form";
  return "Save unfinished form";
}

export function DraftSaveStatus({
  draft,
  command,
  savedAt,
}: {
  draft: string;
  command: string;
  savedAt?: string;
}) {
  return (
    <p role="status" aria-atomic="true" className="command-save-status">
      {formStatus(draft, command)}
      {draft === "saved" &&
        savedAt &&
        command !== "submitting" &&
        command !== "outcome_unknown" && (
          <>
            {" · "}
            <time dateTime={savedAt} title={formatHomeTime(savedAt)}>
              {new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" }).format(
                new Date(savedAt),
              )}
            </time>
          </>
        )}
    </p>
  );
}
