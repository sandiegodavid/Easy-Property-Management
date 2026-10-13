import { Link } from "react-router-dom";
import type { components } from "@epm/contracts/generated";
import { useWorkspace } from "../app/workspace-gate";
import { workflowUrl } from "./command";

export function LeaseDocuments({
  leaseId,
  entityId,
  entityType,
  files,
}: {
  leaseId: string;
  entityId: string;
  entityType: "lease" | "lease_termination_case";
  files: components["schemas"]["LeaseFileResponse"][];
}) {
  const { scope } = useWorkspace();
  const title = entityType === "lease" ? "Lease documents" : "Termination documents";
  return (
    <section aria-label={`${title} ${entityId}`}>
      <h3>{title}</h3>
      <p>
        Documents remain retained evidence. Uploading a document does not execute a Lease or accept
        a termination agreement.
      </p>
      {scope.canWrite && (
        <Link
          to={`${workflowUrl("file.upload")}&${new URLSearchParams({ leaseId, entityType, entityId })}`}
        >
          {entityType === "lease" ? "Attach lease document" : "Attach termination document"}
        </Link>
      )}
      {!files.length && <p>No current {title.toLowerCase()}.</p>}
      <ul>
        {files.map((file) => (
          <li key={file.linkId}>
            {file.originalName} · {file.purpose.replaceAll("_", " ")} · {file.storageState}
            {file.available ? (
              <a href={`/api/files/${file.id}/content`}>Download {file.originalName}</a>
            ) : (
              <p>Content unavailable; opening disabled.</p>
            )}
            <Link to={`/money?file=${file.id}`}>Metadata and history: {file.originalName}</Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
