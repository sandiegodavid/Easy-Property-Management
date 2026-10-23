import type { components } from "@epm/contracts/generated";
import { FileDownload } from "../shared/file-download";
import { SourceWorkflowLink as Link } from "../shared/home-navigation";
import { formatHomeTime } from "../shared/home-time";
import { EvidenceItem } from "./evidence-item";
import { ReadableFacts } from "./readable-facts";

type Schema = components["schemas"];
const words = (text: string) =>
  text.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());

export function ImportedEvidence({
  evidence,
  attachments,
  historical = false,
  downloadsAllowed = false,
}: {
  evidence: Schema["app__modules__intake__api__responses__EvidenceResponse"];
  attachments: Schema["AttachmentResponse"][];
  historical?: boolean;
  downloadsAllowed?: boolean;
}) {
  const Heading = historical ? "h5" : "h3";
  const Subheading = historical ? "h6" : "h4";
  return (
    <article
      className="imported-message-card"
      aria-label={historical ? "Historical imported evidence" : "Imported evidence"}
    >
      <header className="imported-message-heading">
        <Heading>{evidence.subject || "Imported evidence"}</Heading>
        <span className="record-pill">{words(evidence.channel)}</span>
      </header>
      <p className="conversation-detail-time">
        <time dateTime={evidence.occurredAtUtc}>{formatHomeTime(evidence.occurredAtUtc)}</time>
      </p>
      <section
        aria-label={historical ? "Historical evidence participants" : "Evidence participants"}
      >
        <Subheading>Participants</Subheading>
        {!evidence.participants.length && <p>No participants recorded.</p>}
        <ul className="imported-message-participants">
          {evidence.participants.map((participant, index) => (
            <li key={index}>
              <span className="imported-participant-role">{words(participant.role)}</span>
              <strong>
                {participant.display || participant.address || "Participant name not supplied"}
              </strong>
              {participant.display && participant.address && <span>{participant.address}</span>}
            </li>
          ))}
        </ul>
        {!!evidence.participants.length && (
          <p className="record-detail-note">
            Participant details are reported by the source, not verified identities.
          </p>
        )}
      </section>
      <section
        className="imported-message-body"
        aria-label={historical ? "Historical message" : "Message"}
      >
        <Subheading>Message</Subheading>
        <p className="record-narrative">{evidence.body || "No message recorded."}</p>
      </section>
      <section aria-label={historical ? "Historical evidence attachments" : "Evidence attachments"}>
        <Subheading>Attachments</Subheading>
        {!attachments.length && <p>No attachments.</p>}
        {attachments.map((entry) => (
          <EvidenceItem
            key={entry.fileLinkId}
            name={entry.file?.original_name ?? `Attachment ${entry.displayOrder + 1}`}
            state={entry.file?.storage_state ?? "Metadata unavailable"}
          >
            <p className="evidence-item-note">
              {entry.displayOrder + 1} · {words(entry.role)}
              {entry.file
                ? ` · ${entry.file.media_type} · ${entry.file.size_bytes.toLocaleString()} bytes`
                : ""}
            </p>
            {entry.file ? (
              <>
                {!historical &&
                  (downloadsAllowed && entry.file.storage_state === "available" ? (
                    <FileDownload fileId={entry.file.file_id} name={entry.file.original_name}>
                      Download {entry.file.original_name}
                    </FileDownload>
                  ) : (
                    <span>Content unavailable; opening is disabled.</span>
                  ))}
                <Link to={`/money?file=${entry.file.file_id}`}>
                  Metadata and history: {entry.file.original_name}
                </Link>
                <details className="imported-verification">
                  <summary>File verification details</summary>
                  <ReadableFacts value={entry.file} fields={["content_sha256", "verified_at"]} />
                </details>
              </>
            ) : (
              <p>Attachment metadata unavailable.</p>
            )}
          </EvidenceItem>
        ))}
      </section>
      <details className="imported-origin">
        <summary>Original timing and source references</summary>
        <ReadableFacts
          value={evidence}
          fields={["occurredAtContext", "provider", "conversationRef", "externalSourceId"]}
        />
      </details>
    </article>
  );
}
