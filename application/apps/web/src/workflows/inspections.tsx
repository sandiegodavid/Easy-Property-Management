import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useParams, useSearchParams } from "react-router-dom";
import { ParentBackLink, SourceWorkflowLink as Link } from "../shared/home-navigation";
import { api } from "@epm/contracts";
import { record, workflows, type Workflow } from "@epm/contracts/workflows";
import type { components } from "@epm/contracts/generated";
import { useWorkspace } from "../app/workspace-gate";
import { CommandLinks, CommandLoader, workflowUrl } from "./command";
import { Facts, History, readResult } from "./reads";

type Report = components["schemas"]["ReportResponse"];
type Lease = components["schemas"]["LeaseResponse"];
type Template = components["schemas"]["TemplateResponse"];
const reportKindLabels: Record<Report["reportKind"], string> = {
  pre_move_in: "Move-in",
  post_move_out: "Move-out",
};

export function InspectionList({ lease }: { lease: Lease }) {
  const { scope } = useWorkspace();
  const reports = useQuery({
    queryKey: scope.key("inspection-list", lease.id),
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/leases/{lease_id}/condition-reports", {
          signal,
          params: { path: { lease_id: lease.id } },
        }),
      ),
  });
  return (
    <section aria-label="Lease inspections">
      <h3>Inspections</h3>
      <Facts
        value={reports.data?.attention ?? lease.inspectionAttention}
        fields={["preMoveIn", "postMoveOut"]}
      />
      {["executed", "ended", "terminated"].includes(lease.status) && (
        <CommandLinks
          target={lease.id}
          keys={["inspection.report.create", "inspection.comparison.review"]}
          title="Inspection actions"
        />
      )}
      {reports.isPending && <p role="status">Loading inspection reports…</p>}
      {reports.error && (
        <p role="alert">
          Inspections are unavailable: {reports.error.message}. The Lease result remains committed.
        </p>
      )}
      {reports.data?.reports.length === 0 && <p>No inspection reports recorded.</p>}
      {reports.data?.reports.map((report) => (
        <p key={report.id}>
          <Link to={`/inspections/${report.id}`}>
            {reportKindLabels[report.reportKind]} · {report.walkthroughOn} · {report.status}
          </Link>
        </p>
      ))}
    </section>
  );
}

export function InspectionWorkspace() {
  const { id } = useParams();
  const [params] = useSearchParams();
  return params.get("workflow") === "file.link.archive" ? (
    <EvidenceArchive key={params.toString()} />
  ) : params.has("workflow") ? (
    <InspectionCommand key={params.toString()} />
  ) : id ? (
    <ReportRecord id={id} />
  ) : (
    <TemplateDirectory />
  );
}
function TemplateDirectory() {
  const { scope } = useWorkspace();
  const templates = useQuery({
    queryKey: scope.key("inspection-templates"),
    queryFn: async ({ signal }) =>
      readResult(await api.GET("/api/condition-checklist-templates", { signal })),
  });
  return (
    <section aria-label="Inspection templates">
      <ParentBackLink to="/leasing">← Back to Leasing</ParentBackLink>
      <h2>Inspection templates</h2>
      <CommandLinks keys={["inspection.template.create"]} title="Template actions" />
      {templates.isPending && <p role="status">Loading templates…</p>}
      {templates.error && <p role="alert">{templates.error.message}</p>}
      {templates.data?.map((item) => (
        <article key={item.id}>
          <h3>{item.displayName}</h3>
          <Facts value={item} fields={["applicability", "revision", "notes", "archivedAt"]} />
          {item.items.map((observation) => (
            <p key={observation.id}>
              {observation.areaDisplayName} · {observation.itemName}
            </p>
          ))}
          {!item.archivedAt && (
            <CommandLinks
              target={item.id}
              keys={["inspection.template.patch"]}
              title={`Edit ${item.displayName}`}
            />
          )}
        </article>
      ))}
    </section>
  );
}

function ReportRecord({ id }: { id: string }) {
  const { scope } = useWorkspace();
  const report = useQuery({
    queryKey: scope.key("inspection-record", id),
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/condition-reports/{report_id}", {
          signal,
          params: { path: { report_id: id } },
        }),
      ),
  });
  if (report.isPending || report.error)
    return (
      <>
        <ParentBackLink to="/leasing">← Back to Leasing</ParentBackLink>
        {report.error ? (
          <p role="alert">{report.error.message}</p>
        ) : (
          <p role="status">Loading inspection…</p>
        )}
      </>
    );
  const item = report.data;
  return (
    <section aria-label="Inspection report">
      <ParentBackLink to={`/leases/${item.leaseId}/inspections`}>
        ← Back to lease inspections
      </ParentBackLink>
      <h2>{reportKindLabels[item.reportKind]} inspection</h2>
      <Facts
        value={item}
        fields={[
          "status",
          "revision",
          "spaceId",
          "walkthroughOn",
          "conductedBy",
          "tenantPresence",
          "generalNotes",
          "acknowledgmentComplete",
          "timingExceptionReason",
          "correctionReason",
          "finalizedAt",
        ]}
      />
      <p>
        Report finalization preserves condition evidence. It does not complete move-out or approve
        deposit deductions.
      </p>
      <CommandLinks
        target={id}
        keys={
          item.status === "draft"
            ? [
                "inspection.report.patch",
                "inspection.report.areas.replace",
                "inspection.report.acknowledge",
                "inspection.report.finalize",
              ]
            : item.status === "finalized"
              ? ["inspection.report.correct"]
              : []
        }
        title="Report actions"
      />
      {item.supersedesReportId && (
        <Link to={`/inspections/${item.supersedesReportId}`}>
          Prior report and correction history
        </Link>
      )}
      {item.areas.map((area) => (
        <article key={area.id}>
          <h3>{area.displayName}</h3>
          <p>{area.notes}</p>
          {area.observations.map((observation) => (
            <section key={observation.id} aria-label={observation.itemName}>
              <h4>{observation.itemName}</h4>
              <Facts
                value={observation}
                fields={[
                  "conditionState",
                  "cleanlinessState",
                  "observedOn",
                  "isCompleted",
                  "notes",
                ]}
              />
              {item.status === "draft" && (
                <Link
                  to={`${workflowUrl("inspection.evidence.attach", observation.id)}&report=${id}`}
                >
                  Attach evidence for {observation.itemName}
                </Link>
              )}
              {observation.files.map((file) => (
                <p key={file.id}>
                  {file.originalName} · {file.storageState}{" "}
                  <Link to={`/money?file=${file.id}`}>
                    Metadata and history: {file.originalName}
                  </Link>{" "}
                  {file.available ? (
                    <a href={`/api/files/${file.id}/content`}>Download {file.originalName}</a>
                  ) : (
                    <span>Content unavailable; opening disabled.</span>
                  )}
                  {item.status === "draft" &&
                    file.links
                      .filter((link) => link.entityId === observation.id && !link.archivedAt)
                      .map((link) => (
                        <Link key={link.id} to={workflowUrl("file.link.archive", link.id)}>
                          Archive evidence association for {file.originalName}
                        </Link>
                      ))}
                </p>
              ))}
            </section>
          ))}
        </article>
      ))}
      <h3>Acknowledgments</h3>
      {item.acknowledgments.map((ack) => (
        <Facts key={ack.id} value={ack} fields={["leaseParticipantId", "status", "notes"]} />
      ))}
      <History kind="condition_report" id={id} />
    </section>
  );
}

function EvidenceArchive() {
  const [params] = useSearchParams();
  const target = params.get("target");
  const { scope } = useWorkspace();
  const [session] = useState(() => crypto.randomUUID());
  const result = useQuery({
    queryKey: scope.key("evidence-archive-command-source", session, target),
    enabled: !!target,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    queryFn: async ({ signal }) => {
      const link = readResult(
        await api.GET("/api/file-links/{link_id}", {
          signal,
          params: { path: { link_id: target! } },
        }),
      );
      if (link.entityType !== "condition_observation")
        throw new Error("Select evidence visible in an inspection report.");
      const report = readResult(
        await api.GET("/api/condition-observations/{observation_id}/report", {
          signal,
          params: { path: { observation_id: link.entityId } },
        }),
      );
      return { link, report };
    },
  });
  if (!target) return <p role="alert">Select the evidence association first.</p>;
  if (result.isPending) return <p role="status">Loading evidence association…</p>;
  if (result.error) return <p role="alert">{result.error.message}</p>;
  const { link, report } = result.data;
  if (!params.has("resume") && (link.archivedAt || report.status !== "draft"))
    return (
      <p role="alert">Only active evidence associations on a draft inspection can be archived.</p>
    );
  return (
    <>
      <ParentBackLink to={`/inspections/${report.id}`} />
      <p>
        Archiving removes this association from current evidence. The file, reason and history
        remain retained.
      </p>
      <CommandLoader
        definition={workflows.find((item) => item.formKey === "file.link.archive")!}
        sourceId={target}
        revision={link.revision}
        showParentLink={false}
        returnTo={`/inspections/${report.id}`}
        reviewSource={async () => {
          const current = readResult(
            await api.GET("/api/file-links/{link_id}", { params: { path: { link_id: target } } }),
          );
          return { revision: current.revision, value: current };
        }}
      />
    </>
  );
}

function areasForReport(report: Report) {
  return report.areas.map((area) => ({
    displayName: area.displayName,
    notes: area.notes,
    observations: area.observations.map((o) => ({
      itemName: o.itemName,
      conditionState: o.conditionState,
      cleanlinessState: o.cleanlinessState,
      observedOn: o.observedOn,
      isCompleted: o.isCompleted,
      notes: o.notes,
    })),
  }));
}
function areasForTemplate(template: Template) {
  const areas = new Map<
    string,
    { displayName: string; observations: { itemName: string; conditionState: string }[] }
  >();
  for (const item of template.items) {
    if (!areas.has(item.areaDisplayName))
      areas.set(item.areaDisplayName, { displayName: item.areaDisplayName, observations: [] });
    areas
      .get(item.areaDisplayName)!
      .observations.push({ itemName: item.itemName, conditionState: "not_tested" });
  }
  return [...areas.values()];
}

async function inspectionSource(definition: Workflow, target?: string, signal?: AbortSignal) {
  if (
    definition.sourceKind === "condition_report" ||
    definition.sourceKind === "condition_observation"
  ) {
    const report =
      definition.sourceKind === "condition_observation"
        ? readResult(
            await api.GET("/api/condition-observations/{observation_id}/report", {
              signal,
              params: { path: { observation_id: target! } },
            }),
          )
        : readResult(
            await api.GET("/api/condition-reports/{report_id}", {
              signal,
              params: { path: { report_id: target! } },
            }),
          );
    const initial: Record<string, unknown> = {};
    if (definition.formKey.endsWith(".patch") || definition.formKey.endsWith(".correct"))
      for (const key of Object.keys(definition.schema.properties ?? {}))
        if (key in report && !key.startsWith("expected") && key !== "correctionReason")
          initial[key] = record(report)[key];
    if (definition.formKey.endsWith(".correct") || definition.formKey.includes("areas"))
      initial.areas = areasForReport(report);
    let schema = definition.schema;
    if (definition.formKey.endsWith(".acknowledge")) {
      const leases = readResult(
        await api.GET("/api/leases/{lease_id}", {
          signal,
          params: { path: { lease_id: report.leaseId } },
        }),
      );
      const ack = definition.schema.properties!.acknowledgments;
      const item = typeof ack.additionalProperties === "object" ? ack.additionalProperties : {};
      const participants = leases.participants.filter(
        (p) => p.startsOn <= report.walkthroughOn && (!p.endsOn || p.endsOn > report.walkthroughOn),
      );
      const activeIds = new Set(participants.map((p) => p.id));
      schema = {
        ...schema,
        properties: {
          ...schema.properties,
          acknowledgments: {
            type: "object",
            additionalProperties: false,
            required: participants.map((p) => p.id),
            properties: Object.fromEntries(
              participants.map((p) => [
                p.id,
                {
                  ...item,
                  title: `${p.participantRole.replaceAll("_", " ")}: ${p.tenantPartyId} (${p.startsOn} – ${p.endsOn ?? "open"})`,
                },
              ]),
            ),
          },
        },
      };
      initial.acknowledgments = Object.fromEntries(
        report.acknowledgments
          .filter((a) => activeIds.has(a.leaseParticipantId))
          .map((a) => [a.leaseParticipantId, { status: a.status, notes: a.notes }]),
      );
    }
    return {
      revision: report.revision,
      initial,
      value: report,
      report,
      template: null,
      comparison: null,
      schema,
      returnTo: `/inspections/${report.id}`,
    };
  }
  if (definition.sourceKind === "condition_template") {
    const templates = readResult(await api.GET("/api/condition-checklist-templates", { signal }));
    const template = templates.find((item) => item.id === target);
    if (!template) throw new Error("Inspection template not found.");
    return {
      revision: template.revision,
      initial: {
        displayName: template.displayName,
        applicability: template.applicability,
        notes: template.notes,
        areas: areasForTemplate(template),
      },
      value: template,
      template,
      report: null,
      comparison: null,
      schema: definition.schema,
      returnTo: "/leasing?templates=true",
    };
  }
  if (definition.sourceKind === "inspection_lease") {
    const reports = readResult(
      await api.GET("/api/leases/{lease_id}/condition-reports", {
        signal,
        params: { path: { lease_id: target! } },
      }),
    );
    const comparison =
      definition.formKey === "inspection.comparison.review"
        ? readResult(
            await api.GET("/api/leases/{lease_id}/condition-comparison", {
              signal,
              params: { path: { lease_id: target! } },
            }),
          )
        : null;
    return {
      revision: reports.revision,
      initial: comparison
        ? {
            comparisons: comparison.comparisons.map((c) => ({
              preObservationId: c.preObservationId,
              postObservationId: c.postObservationId,
              comparisonState: c.comparisonState,
              operatorNotes: c.operatorNotes,
            })),
          }
        : { reportKind: "pre_move_in", areas: [] },
      value: reports,
      template: null,
      report: null,
      comparison,
      schema: definition.schema,
      returnTo: `/leases/${target}/inspections`,
    };
  }
  return {
    revision: 0,
    initial: { applicability: "any", areas: [] },
    value: {},
    template: null,
    report: null,
    comparison: null,
    schema: definition.schema,
    returnTo: "/leasing?templates=true",
  };
}

function InspectionCommand() {
  const [params] = useSearchParams();
  const definition = workflows.find((item) => item.formKey === params.get("workflow"))!;
  const target = params.get("target") ?? undefined;
  const { scope } = useWorkspace();
  const [session] = useState(() => crypto.randomUUID());
  const source = useQuery({
    queryKey: scope.key("inspection-command-source", session, target),
    enabled: !definition.sourceKind || !!target,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    queryFn: ({ signal }) => inspectionSource(definition, target, signal),
  });
  const templates = useQuery({
    queryKey: scope.key("inspection-template-choices"),
    enabled: definition.formKey === "inspection.report.create",
    queryFn: async ({ signal }) =>
      readResult(await api.GET("/api/condition-checklist-templates", { signal })),
  });
  if (!definition.formKey.startsWith("inspection."))
    return <p role="alert">Unsupported inspection workflow.</p>;
  if (definition.sourceKind && !target)
    return <p role="alert">Select the owning inspection record first.</p>;
  if (source.isPending) return <p role="status">Loading displayed inspection…</p>;
  if (source.error) return <p role="alert">{source.error.message}</p>;
  const item = source.data;
  const choices = {
    templateId:
      templates.data
        ?.filter((t) => !t.archivedAt)
        .map((t) => ({ id: t.id, label: t.displayName })) ?? [],
    preObservationId:
      item.comparison?.preReport?.areas.flatMap((a) =>
        a.observations.map((o) => ({
          id: o.id,
          label: `${a.displayName}: ${o.itemName} · ${o.conditionState}`,
        })),
      ) ?? [],
    postObservationId:
      item.comparison?.postReport?.areas.flatMap((a) =>
        a.observations.map((o) => ({
          id: o.id,
          label: `${a.displayName}: ${o.itemName} · ${o.conditionState}`,
        })),
      ) ?? [],
  };
  return (
    <>
      <ParentBackLink to={item.returnTo} />
      {templates.error && (
        <p role="alert">Template choices are unavailable: {templates.error.message}</p>
      )}
      {item.comparison && (
        <>
          <p>
            {item.comparison.requiresFreshReview
              ? "The report pair changed; review the current evidence again."
              : "Review condition evidence; comparisons do not create deductions."}
          </p>
          {[item.comparison.preReport, item.comparison.postReport].map(
            (report) =>
              report && (
                <p key={report.id}>
                  <Link to={`/inspections/${report.id}`}>
                    {reportKindLabels[report.reportKind]} evidence
                  </Link>
                </p>
              ),
          )}
        </>
      )}
      <CommandLoader
        showParentLink={false}
        definition={{ ...definition, schema: item.schema }}
        sourceId={target}
        revision={item.revision}
        initial={item.initial}
        choices={choices}
        returnTo={item.returnTo}
        reviewSource={async () => {
          const current = await inspectionSource(definition, target);
          return { revision: current.revision, value: current.value };
        }}
      />
    </>
  );
}
