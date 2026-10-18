import { DynamicFilterForm } from "../shared/dynamic-filter-form";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ParentBackLink, SourceWorkflowLink as Link } from "../shared/home-navigation";
import { api } from "@epm/contracts";
import type { components } from "@epm/contracts/generated";
import { workflows } from "@epm/contracts/workflows";
import { useWorkspace } from "../app/workspace-gate";
import { CommandLinks, CommandLoader } from "./command";
import { Facts, readResult } from "./reads";
import { label } from "./fields";

type Source = components["schemas"]["SourceDetailResponse"];

async function detail(id: string, signal?: AbortSignal): Promise<Source> {
  // This source-owned endpoint commits its sensitive-read audit before disclosure.
  return readResult(
    await api.GET("/api/intake/sources/{source_id}", {
      signal,
      params: { path: { source_id: id } },
    }),
  );
}

export function IntakeWorkspace() {
  const [params] = useSearchParams();
  const back = new URLSearchParams(params);
  back.delete("source");
  return (
    <section aria-label="Retained Intake sources">
      {!params.has("source") && !params.has("workflow") && (
        <ParentBackLink to="/conversations">← Back to Conversations</ParentBackLink>
      )}
      {params.has("source") && !params.has("workflow") && (
        <ParentBackLink to={`/conversations?${back}`}>← Back to source directory</ParentBackLink>
      )}
      {!params.has("workflow") && (
        <>
          <h2>Retained source evidence</h2>
          <p>
            Manual evidence is an unverified claim. Retaining or reviewing it does not send a
            message, create an issue, or establish that work occurred.
          </p>
          <nav className="page-tabs" aria-label="Source views">
            <Link to="/conversations?intake=true" aria-current="page">
              Source directory
            </Link>
            <Link to="/conversations">Recorded conversations</Link>
          </nav>
        </>
      )}
      {params.has("workflow") ? (
        <IntakeCommand key={params.toString()} />
      ) : params.has("source") ? (
        <SourceDetail key={params.get("source")} id={params.get("source")!} />
      ) : (
        <SourceDirectory />
      )}
    </section>
  );
}

function SourceDirectory() {
  const { scope } = useWorkspace();
  const [params, setParams] = useSearchParams();
  const loaded = useQuery({
    queryKey: scope.key("intake-directory", params.toString()),
    retry: false,
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/intake/sources", {
          signal,
          params: {
            query: {
              limit: 25,
              cursor: params.get("cursor") ?? undefined,
              sourceKind: params.get("sourceKind") ?? undefined,
              channel: params.get("channel") ?? undefined,
              technicalStatus: params.get("technicalStatus") ?? undefined,
              attentionStatus: params.get("attentionStatus") ?? undefined,
              originSystem: params.get("originSystem") ?? undefined,
              accountIdentityState: params.get("accountIdentityState") ?? undefined,
              receivedFrom: params.get("receivedFrom") ?? undefined,
              receivedTo: params.get("receivedTo") ?? undefined,
              hasDuplicate:
                params.get("hasDuplicate") === "true"
                  ? true
                  : params.get("hasDuplicate") === "false"
                    ? false
                    : undefined,
            },
          },
        }),
      ),
  });
  const choices = {
    sourceKind: [
      "email_message",
      "sms_message",
      "chat_message",
      "operator_note",
      "voice_transcript",
    ],
    channel: ["email", "sms", "chat", "internal", "voice"],
    technicalStatus: ["ready", "failed", "superseded"],
    attentionStatus: ["unprocessed", "in_review", "resolved", "dismissed"],
    accountIdentityState: [
      "transport_verified",
      "operator_confirmed",
      "unverified_claim",
      "not_applicable",
    ],
    hasDuplicate: ["true", "false"],
  };
  return (
    <>
      <CommandLinks
        keys={["intake.source.admit", "intake.source.import"]}
        title="Retain evidence"
      />
      <DynamicFilterForm
        className="read-filters"
        onSubmit={(event) => {
          event.preventDefault();
          const data = new FormData(event.currentTarget);
          const next = new URLSearchParams({ intake: "true" });
          for (const [key, value] of data)
            if (typeof value === "string" && value) next.set(key, value);
          setParams(next, { replace: true, preventScrollReset: true });
        }}
      >
        {Object.entries(choices).map(([key, values]) => (
          <label key={key}>
            {label(key)}
            <select name={key} defaultValue={params.get(key) ?? ""}>
              <option value="">All</option>
              {values.map((value) => (
                <option key={value}>{value}</option>
              ))}
            </select>
          </label>
        ))}
        {["originSystem", "receivedFrom", "receivedTo"].map((key) => (
          <label key={key}>
            {label(key)}
            <input
              name={key}
              defaultValue={params.get(key) ?? ""}
              placeholder={key === "originSystem" ? undefined : "ISO timestamp with offset"}
              pattern={
                key === "originSystem"
                  ? undefined
                  : "\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}(:\\d{2}(\\.\\d{1,6})?)?(Z|\\+\\d{2}:\\d{2}|-\\d{2}:\\d{2})"
              }
            />
          </label>
        ))}
      </DynamicFilterForm>
      {loaded.isPending && <p role="status">Loading retained sources…</p>}
      {loaded.error && (
        <>
          <p role="alert">Sources unavailable: {loaded.error.message}</p>
          <button onClick={() => void loaded.refetch()}>Retry sources</button>
        </>
      )}
      {!loaded.error && loaded.data && (
        <>
          <p>
            {loaded.data.items.length} sources on this bounded page. Source evidence opens through
            an audited read.
          </p>
          {!loaded.data.items.length && <p>No sources match these filters.</p>}
          <ul>
            {loaded.data.items.map((item) => (
              <li key={item.sourceId}>
                <Link to={`/conversations?${params.toString()}&source=${item.sourceId}`}>
                  {item.sourceKind} · {item.occurredAtUtc}
                </Link>
                <Facts
                  value={item}
                  fields={[
                    "sourceId",
                    "channel",
                    "technicalStatus",
                    "attentionStatus",
                    "sourceRevision",
                    "attachmentCount",
                    "receivedAtUtc",
                  ]}
                />
                <Facts
                  value={item.provenance}
                  fields={["originSystem", "accountIdentityState", "submitterKind"]}
                />
              </li>
            ))}
          </ul>
          {loaded.data.nextCursor && (
            <button
              onClick={() => {
                const next = new URLSearchParams(params);
                next.set("cursor", loaded.data.nextCursor ?? "");
                setParams(next);
              }}
            >
              Next sources
            </button>
          )}
        </>
      )}
      {params.has("cursor") && (
        <button
          onClick={() => {
            const next = new URLSearchParams(params);
            next.delete("cursor");
            setParams(next);
          }}
        >
          First source page
        </button>
      )}
    </>
  );
}

function SourceDetail({ id }: { id: string }) {
  const { scope } = useWorkspace();
  const [revisionId, setRevisionId] = useState<string | null>(null);
  const loaded = useQuery({
    queryKey: scope.key("intake-sensitive-detail", id),
    queryFn: ({ signal }) => detail(id, signal),
    retry: false,
    gcTime: 0,
  });
  if (loaded.isPending) return <p role="status">Authorizing audited evidence read…</p>;
  if (loaded.error)
    return (
      <>
        <p role="alert">
          Source evidence unavailable: {loaded.error.message}. Evidence is withheld when its
          required audit cannot commit.
        </p>
        <button onClick={() => void loaded.refetch()}>Retry audited evidence read</button>
      </>
    );
  const item = loaded.data;
  return (
    <section aria-label="Source evidence detail">
      <Facts
        value={item}
        fields={[
          "sourceId",
          "sourceRevision",
          "technicalStatus",
          "failureCode",
          "attentionStatus",
          "supersedesSourceId",
          "supersededBySourceId",
        ]}
      />
      <CommandLinks
        target={id}
        keys={
          item.technicalStatus === "ready"
            ? [
                "intake.source.correct",
                "intake.source.supersede",
                ...(item.attentionStatus === "dismissed"
                  ? ["intake.source.reopen"]
                  : ["unprocessed", "in_review"].includes(item.attentionStatus)
                    ? ["intake.source.dismiss"]
                    : []),
              ]
            : []
        }
      />
      {item.supersededBySourceId && (
        <Link to={`/conversations?intake=true&source=${item.supersededBySourceId}`}>
          Open replacement source
        </Link>
      )}
      <h3>Retained evidence</h3>
      <Facts
        value={item.evidence}
        fields={[
          "subject",
          "body",
          "occurredAtUtc",
          "occurredAtContext",
          "provider",
          "conversationRef",
          "externalSourceId",
        ]}
      />
      <h3>Participants</h3>
      {item.evidence.participants.map((participant, index) => (
        <Facts key={index} value={participant} fields={["role", "display", "address"]} />
      ))}
      <h3>Attachments</h3>
      {item.attachments.map((entry) => (
        <div key={entry.fileLinkId}>
          <p>
            {entry.displayOrder + 1} · {entry.role}
          </p>
          {entry.file ? (
            <>
              <Facts
                value={entry.file}
                fields={[
                  "original_name",
                  "media_type",
                  "size_bytes",
                  "content_sha256",
                  "storage_state",
                  "verified_at",
                ]}
              />
              {item.technicalStatus !== "failed" && entry.file.storage_state === "available" ? (
                <a href={`/api/files/${entry.file.file_id}/content`} download>
                  Download {entry.file.original_name}
                </a>
              ) : (
                <p>Content unavailable; opening is disabled.</p>
              )}
            </>
          ) : (
            <p>Attachment metadata unavailable.</p>
          )}
        </div>
      ))}
      <h3>Retained revision history</h3>
      {item.revisions.map((revision) => (
        <div key={revision.id}>
          <Facts
            value={revision}
            fields={["id", "number", "kind", "createdAt", "correctionReason"]}
          />
          <button onClick={() => setRevisionId(revision.id)}>
            Read retained revision {revision.number}
          </button>
        </div>
      ))}
      {revisionId && (
        <RetainedRevision key={`${id}:${revisionId}`} sourceId={id} revisionId={revisionId} />
      )}
      <h3>Operation history</h3>
      {item.operations.map((operation, index) => (
        <Facts key={index} value={operation} fields={["type", "outcome", "createdAt"]} />
      ))}
      <h3>Duplicate candidates</h3>
      {item.duplicateCandidates.map((candidate) => (
        <p key={candidate.candidateSourceId}>
          <Link to={`/conversations?intake=true&source=${candidate.candidateSourceId}`}>
            Review candidate source
          </Link>{" "}
          · {candidate.reason} · {candidate.disposition}
        </p>
      ))}
    </section>
  );
}

function RetainedRevision({ sourceId, revisionId }: { sourceId: string; revisionId: string }) {
  const { scope } = useWorkspace();
  const loaded = useQuery({
    queryKey: scope.key("intake-sensitive-revision", sourceId, revisionId),
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/intake/sources/{source_id}/revisions/{revision_id}", {
          signal,
          params: { path: { source_id: sourceId, revision_id: revisionId } },
        }),
      ),
    retry: false,
    gcTime: 0,
  });
  return (
    <section aria-label="Selected retained evidence revision">
      <h4>Exact retained evidence — not the current representation</h4>
      {loaded.isPending && <p role="status">Authorizing audited revision read…</p>}
      {loaded.error ? (
        <>
          <p role="alert">Revision evidence is withheld: {loaded.error.message}</p>
          <button onClick={() => void loaded.refetch()}>Retry audited revision read</button>
        </>
      ) : (
        loaded.data && (
          <>
            <Facts
              value={loaded.data}
              fields={[
                "revisionNumber",
                "revisionKind",
                "revisionCreatedAt",
                "correctionReason",
                "fingerprint",
              ]}
            />
            <Facts
              value={loaded.data.evidence}
              fields={["subject", "body", "occurredAtUtc", "occurredAtContext"]}
            />
            {loaded.data.evidence.participants.map((participant, index) => (
              <Facts key={index} value={participant} fields={["role", "display", "address"]} />
            ))}
            {loaded.data.attachments.map((attachment) => (
              <div key={attachment.fileLinkId}>
                <Facts value={attachment} fields={["role", "displayOrder"]} />
                {attachment.file ? (
                  <Facts
                    value={attachment.file}
                    fields={["original_name", "content_sha256", "storage_state", "verified_at"]}
                  />
                ) : (
                  <p>Attachment metadata unavailable.</p>
                )}
              </div>
            ))}
            {(loaded.data.historyTruncated || loaded.data.attachmentsTruncated) && (
              <p>
                This bounded read is incomplete; additional retained history or attachments are not
                shown.
              </p>
            )}
          </>
        )
      )}
    </section>
  );
}

function IntakeCommand() {
  const { scope } = useWorkspace();
  const [params] = useSearchParams();
  const definition = workflows.find((item) => item.formKey === params.get("workflow"));
  const target = params.get("target") ?? undefined;
  const loaded = useQuery({
    queryKey: scope.key("intake-command-source", target),
    enabled: !!target,
    queryFn: ({ signal }) => detail(target!, signal),
    retry: false,
    gcTime: 0,
  });
  const saved = useQuery({
    queryKey: scope.key("workflow-recovery", params.get("resume")),
    enabled: params.has("resume"),
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/operator/recovery/{record_id}", {
          signal,
          params: { path: { record_id: params.get("resume")! } },
        }),
      ),
    retry: false,
  });
  if (!definition?.formKey.startsWith("intake."))
    return <p role="alert">Unknown source command.</p>;
  if (definition.sourceKind && !target)
    return <p role="alert">Select the owning source before this command.</p>;
  if (target && loaded.isPending) return <p role="status">Loading audited source context…</p>;
  const originalOnly =
    saved.data?.formKey === definition.formKey &&
    saved.data.sourceId === (target ?? null) &&
    ["outcome_unknown", "reconciled"].includes(saved.data.status);
  if (loaded.error && params.has("resume") && saved.isPending)
    return <p role="status">Loading original source attempt…</p>;
  if (loaded.error && !originalOnly)
    return <p role="alert">Source evidence unavailable: {loaded.error.message}</p>;
  const current = loaded.data;
  if (current && current.technicalStatus !== "ready" && !originalOnly)
    return (
      <p role="alert">
        This source cannot accept new operator changes. Its original attempt can still be recovered.
      </p>
    );
  const initial = current
    ? {
        ...current.evidence,
        occurredAtUtc: current.evidence.occurredAtContext,
        originSystem: current.provenance.originSystem,
        expectedEvidenceRevisionId: current.evidenceRevisionId,
        expectedStatus: current.attentionStatus,
      }
    : {
        sourceKind: "operator_note",
        channel: "internal",
        originSystem: "local_operator",
        participants: [],
        attachments: [],
      };
  return (
    <CommandLoader
      definition={definition}
      sourceId={target}
      revision={current?.sourceRevision ?? 0}
      initial={initial}
      returnTo={
        target ? `/conversations?intake=true&source=${target}` : "/conversations?intake=true"
      }
      reviewSource={async () => {
        const value = await detail(target!);
        return { revision: value.sourceRevision, value };
      }}
    />
  );
}
