import { DynamicFilterForm } from "../shared/dynamic-filter-form";
import { filterFormData, InstantFilter } from "../shared/instant-filter";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ParentBackLink, SourceWorkflowLink as Link } from "../shared/home-navigation";
import { api } from "@epm/contracts";
import type { components } from "@epm/contracts/generated";
import { workflows } from "@epm/contracts/workflows";
import { useWorkspace } from "../app/workspace-gate";
import { CommandLinks, CommandLoader } from "./command";
import { readResult } from "./reads";
import { label } from "./fields";
import { ReadableFacts } from "./readable-facts";
import { formatHomeTime } from "../shared/home-time";
import { ImportedEvidence } from "./imported-evidence";

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
    <section aria-label="Retained sources">
      {!params.has("source") && !params.has("workflow") && (
        <ParentBackLink to="/conversations">← Back to Conversations</ParentBackLink>
      )}
      {params.has("source") && !params.has("workflow") && (
        <ParentBackLink to={`/conversations?${back}`}>← Back to Retained sources</ParentBackLink>
      )}
      {!params.has("workflow") && (
        <>
          <h2>Retained sources</h2>
          <p>
            Manual evidence is an unverified claim. Retaining or reviewing it does not send a
            message, create an issue, or establish that work occurred.
          </p>
          <nav className="page-tabs" aria-label="Source views">
            <Link to="/conversations?intake=true" aria-current="page">
              Retained sources
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
          const data = filterFormData(event.currentTarget);
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
                <option key={value} value={value}>
                  {value.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase())}
                </option>
              ))}
            </select>
          </label>
        ))}
        <label>
          Origin system
          <input name="originSystem" defaultValue={params.get("originSystem") ?? ""} />
        </label>
        {["receivedFrom", "receivedTo"].map((key) => (
          <InstantFilter key={key} name={key} label={label(key)} value={params.get(key) ?? ""} />
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
            {loaded.data.items.length} retained{" "}
            {loaded.data.items.length === 1 ? "source" : "sources"} on this page.
          </p>
          {!loaded.data.items.length && <p>No sources match these filters.</p>}
          <ul className="work-directory-grid">
            {loaded.data.items.map((item) => (
              <li className="work-directory-card" key={item.sourceId}>
                <h3>
                  <Link to={`/conversations?${params.toString()}&source=${item.sourceId}`}>
                    {label(item.sourceKind.replaceAll("_", " "))} ·{" "}
                    {formatHomeTime(item.occurredAtUtc)}
                  </Link>
                </h3>
                <ReadableFacts
                  value={{ ...item, ...item.provenance }}
                  fields={[
                    "channel",
                    "technicalStatus",
                    "attentionStatus",
                    "attachmentCount",
                    "receivedAtUtc",
                    "originSystem",
                    "accountIdentityState",
                    "submitterKind",
                  ]}
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
          Retained source unavailable: {loaded.error.message}. Evidence is withheld when its
          required audit cannot commit.
        </p>
        <button onClick={() => void loaded.refetch()}>Retry audited evidence read</button>
      </>
    );
  const item = loaded.data;
  return (
    <section className="imported-record-detail" aria-label="Retained source detail">
      <ReadableFacts value={item} fields={["technicalStatus", "failureCode", "attentionStatus"]} />
      <CommandLinks
        asButtons
        collapsible={false}
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
      {item.supersedesSourceId && (
        <p>
          <Link to={`/conversations?intake=true&source=${item.supersedesSourceId}`}>
            View the imported record this replaces
          </Link>
        </p>
      )}
      <ImportedEvidence
        evidence={item.evidence}
        attachments={item.attachments}
        downloadsAllowed={item.technicalStatus !== "failed"}
      />
      <section className="record-detail-block" aria-label="Evidence revision history">
        <h3>Retained revision history</h3>
        {item.revisions.map((revision) => (
          <div className="record-detail-row" key={revision.id}>
            <ReadableFacts
              value={revision}
              fields={["number", "kind", "createdAt", "correctionReason"]}
            />
            <button onClick={() => setRevisionId(revision.id)}>
              Read retained revision {revision.number}
            </button>
          </div>
        ))}
        {revisionId && (
          <RetainedRevision key={`${id}:${revisionId}`} sourceId={id} revisionId={revisionId} />
        )}
      </section>
      <details className="record-detail-block">
        <summary>Operation history ({item.operations.length})</summary>
        {item.operations.map((operation, index) => (
          <div className="record-detail-row" key={index}>
            <ReadableFacts value={operation} fields={["type", "outcome", "createdAt"]} />
          </div>
        ))}
      </details>
      <section className="record-detail-block" aria-label="Possible duplicate records">
        <h3>Duplicate candidates</h3>
        {!item.duplicateCandidates.length && <p>No possible duplicates recorded.</p>}
        {item.duplicateCandidates.map((candidate) => (
          <p key={candidate.candidateSourceId}>
            <Link to={`/conversations?intake=true&source=${candidate.candidateSourceId}`}>
              Review candidate source
            </Link>{" "}
            · {label(candidate.reason.replaceAll("_", " "))} ·{" "}
            {label(candidate.disposition.replaceAll("_", " "))}
          </p>
        ))}
      </section>
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
            <ReadableFacts
              value={loaded.data}
              fields={["revisionNumber", "revisionKind", "revisionCreatedAt", "correctionReason"]}
            />
            <ImportedEvidence
              evidence={loaded.data.evidence}
              attachments={loaded.data.attachments}
              historical
            />
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
    return <p role="alert">Retained source unavailable: {loaded.error.message}</p>;
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
