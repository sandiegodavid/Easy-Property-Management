import { useCallback, useState, type ReactNode } from "react";
import { useWatch } from "react-hook-form";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { SourceWorkflowLink as Link } from "../shared/home-navigation";
import { api } from "@epm/contracts";
import {
  workflows,
  dispatchWorkflow,
  record,
  scalar,
  validateRequest,
  type Workflow,
} from "@epm/contracts/workflows";
import { useQuery } from "@tanstack/react-query";
import { useWorkspace } from "../app/workspace-gate";
import { useRecoverableForm, RecoveryNavigation } from "../shared/use-recoverable-form";
import { mutation } from "../shared/mutations";
import type { Recovery } from "../shared/recovery";
import { clean, Fields, type Choices } from "./fields";
import { Facts, readResult } from "./reads";
import { MoneyFacts } from "./money-presentation";
import { OriginalWorkResult } from "./work-result";
import { TaskCreateFields } from "./task-fields";
import { PropertyEditFields } from "./property-edit-fields";
import { PropertyCreateFields } from "./property-create-fields";

export function workflowUrl(formKey: string, sourceId?: string, childId?: string) {
  const params = new URLSearchParams({ workflow: formKey });
  if (sourceId) params.set("target", sourceId);
  if (childId) params.set("child", childId);
  const family = formKey.startsWith("task.")
    ? "tasks"
    : formKey.startsWith("communication.") || formKey.startsWith("intake.")
      ? "conversations"
      : formKey.startsWith("maintenance.") || formKey.startsWith("owner_concern.")
        ? "maintenance"
        : formKey.startsWith("portfolio.")
          ? "properties"
          : formKey.startsWith("provider.")
            ? "providers"
            : formKey.startsWith("finance.") ||
                formKey.startsWith("owner_rent_report.") ||
                formKey === "file.upload"
              ? "money"
              : formKey.startsWith("lease.") ||
                  formKey.startsWith("inspection.") ||
                  formKey === "file.link.archive"
                ? "leasing"
                : "parties";
  return `/${family}?${params}`;
}

function toPayload(definition: Workflow, body: Record<string, unknown>, child?: string) {
  const values = { ...body };
  delete values.idempotencyKey;
  let payload = values;
  if (definition.formKey.startsWith("lease.")) {
    const { expectedLeaseRevision, expectedRevision, ...rest } = values;
    payload = { ...rest, expectedRevision: expectedLeaseRevision };
    if (expectedRevision !== undefined) payload.expectedSpaceRevision = expectedRevision;
  }
  if (definition.nesting === "changes") {
    const { expectedPropertyRevision, ...changes } = values;
    payload = { expectedPropertyRevision, changes };
  }
  if (definition.nesting === "occupancy") {
    const { occupancy, ...rest } = values;
    payload = { ...record(occupancy), ...rest };
  }
  if (definition.nesting === "financialChanges") {
    const { expectedRevision, ...changes } = values;
    payload = { expectedRevision, changes };
  }
  if (definition.formKey === "owner_rent_report.verify") {
    const { expectedRentLedgerRevision, ...rest } = payload;
    payload = { ...rest, expectedLedgerRevision: expectedRentLedgerRevision };
  }
  if (definition.formKey === "finance.deposit_settlement.complete") {
    const { confirmed, zeroDollarClosureConfirmed, ...rest } = payload;
    void zeroDollarClosureConfirmed;
    payload = { ...rest, ...(confirmed === undefined ? {} : { zeroRefundConfirmed: confirmed }) };
  }
  if (definition.formKey === "finance.rent_receipt.create") delete payload.leaseId;
  if (definition.formKey === "file.upload") delete payload.sizeBytes;
  if (
    definition.formKey === "maintenance.journal.record" &&
    (payload.correctedEntryKind ?? payload.entryKind) === "work_completed"
  ) {
    if (payload.operatorVerified === undefined) payload.operatorVerified = false;
    if (payload.followUpRequired === undefined) payload.followUpRequired = false;
  }
  if (["task.create", "maintenance.issue.create"].includes(definition.formKey))
    delete payload.expectedRevision;
  if (definition.formKey.startsWith("task.waiting.")) {
    const { waitingForKind, waitingForLabel, followUpAt, ...rest } = payload;
    payload = {
      ...rest,
      ...(waitingForKind === undefined ? {} : { kind: waitingForKind }),
      ...(waitingForLabel === undefined ? {} : { label: waitingForLabel }),
      ...(followUpAt === undefined ? {} : { followUpAtUtc: followUpAt }),
    };
  }
  if (definition.childKey) payload[definition.childKey] = child;
  return payload;
}
function toBody(
  definition: Workflow,
  payload: Record<string, unknown>,
  key?: string,
  sourceId?: string,
) {
  const values = { ...payload };
  if (definition.childKey) delete values[definition.childKey];
  let body = values;
  if (definition.formKey.startsWith("lease.")) {
    const { expectedRevision, expectedSpaceRevision, ...rest } = values;
    body = { ...rest, expectedLeaseRevision: expectedRevision };
    if (expectedSpaceRevision !== undefined) body.expectedRevision = expectedSpaceRevision;
  }
  if (definition.nesting === "changes") {
    const { changes, ...rest } = values;
    body = { ...rest, ...record(changes) };
  }
  if (definition.nesting === "occupancy") {
    const { reason, expectedRevision, ...occupancy } = values;
    body = { reason, expectedRevision, occupancy };
  }
  if (definition.nesting === "financialChanges") {
    const { changes, ...rest } = values;
    body = { ...rest, ...record(changes) };
  }
  if (definition.formKey === "owner_rent_report.verify") {
    const { expectedLedgerRevision, ...rest } = body;
    body = { ...rest, expectedRentLedgerRevision: expectedLedgerRevision };
  }
  if (definition.formKey === "finance.deposit_settlement.complete") {
    const { zeroRefundConfirmed, ...rest } = body;
    body = { ...rest, confirmed: zeroRefundConfirmed };
  }
  if (definition.formKey === "finance.rent_receipt.create" && sourceId) body.leaseId = sourceId;
  if (["task.create", "maintenance.issue.create"].includes(definition.formKey))
    body.expectedRevision = 0;
  if (definition.formKey.startsWith("task.waiting.")) {
    const { kind, label, followUpAtUtc, ...rest } = body;
    body = {
      ...rest,
      ...(kind === undefined ? {} : { waitingForKind: kind }),
      ...(label === undefined ? {} : { waitingForLabel: label }),
      ...(followUpAtUtc === undefined ? {} : { followUpAt: followUpAtUtc }),
    };
  }
  return key ? { ...body, idempotencyKey: key } : body;
}

export function CommandLinks({
  keys,
  target,
  child,
  title = "Actions",
  labels = {},
  collapsible = true,
  asButtons = false,
}: {
  keys: string[];
  target?: string;
  child?: string;
  title?: string;
  labels?: Record<string, string>;
  collapsible?: boolean;
  asButtons?: boolean;
}) {
  const { scope } = useWorkspace();
  const location = useLocation();
  const navigate = useNavigate();
  if (!scope.canWrite) return <p>Workspace writes are unavailable.</p>;
  const actions = (
    <nav aria-label={title} className={collapsible ? undefined : "workflow-actions-inline"}>
      {keys.map((key) => {
        const definition = workflows.find((item) => item.formKey === key);
        return (
          definition &&
          (asButtons ? (
            <button
              key={key}
              type="button"
              onClick={() => {
                void navigate(workflowUrl(key, target, child), {
                  state: { returnTo: location.pathname + location.search },
                });
              }}
            >
              {labels[key] ?? definition.title}
            </button>
          ) : (
            <Link
              key={key}
              to={workflowUrl(key, target, child)}
              state={{ returnTo: location.pathname + location.search }}
            >
              {labels[key] ?? definition.title}
            </Link>
          ))
        );
      })}
    </nav>
  );
  return collapsible ? (
    <details className="workflow-actions">
      <summary>{title}</summary>
      {actions}
    </details>
  ) : (
    actions
  );
}

export function CommandLoader({
  definition,
  sourceId,
  childId,
  revision,
  initial = {},
  choices = {},
  choicesForValues,
  returnTo,
  reviewSource,
  checkSource,
  renderContext,
  canSubmit,
}: {
  definition: Workflow;
  sourceId?: string;
  childId?: string;
  revision: number;
  initial?: Record<string, unknown>;
  choices?: Choices;
  choicesForValues?: (values: Record<string, unknown>) => Choices;
  returnTo?: string;
  reviewSource?: () => Promise<{
    revision: number;
    value: unknown;
    relatedRevisions?: Record<string, number>;
  }>;
  checkSource?: (values: Record<string, unknown>) => Promise<void>;
  canSubmit?: (values: Record<string, unknown>) => boolean;
  renderContext?: (
    values: Record<string, unknown>,
    locked: boolean,
    onChange: (values: Record<string, unknown>) => void,
  ) => ReactNode;
}) {
  const { scope } = useWorkspace();
  const [params] = useSearchParams();
  const recoveryId = params.get("resume");
  const recovery = useQuery({
    queryKey: scope.key("workflow-recovery", recoveryId),
    enabled: !!recoveryId,
    queryFn: async ({ signal }) => {
      const response = await api.GET("/api/operator/recovery/{record_id}", {
        signal,
        params: { path: { record_id: recoveryId! } },
      });
      if (!response.data) throw new Error("Could not load this unfinished form.");
      if (
        response.data.formKey !== definition.formKey ||
        response.data.sourceId !== (sourceId ?? null)
      )
        throw new Error("This form belongs to a different workflow or source.");
      return response.data;
    },
  });
  if (recoveryId && recovery.isPending) return <p role="status">Loading unfinished form…</p>;
  if (recovery.error) return <p role="alert">{recovery.error.message}</p>;
  const selectedChild =
    childId ??
    (definition.childKey && recovery.data
      ? scalar(recovery.data.payload[definition.childKey])
      : undefined);
  return (
    <CommandEditor
      key={`${scope.workspaceId}:${scope.runtimeEpoch}:${definition.formKey}:${sourceId}:${selectedChild}:${recoveryId}`}
      definition={definition}
      sourceId={sourceId}
      childId={selectedChild}
      revision={revision}
      initial={initial}
      choices={choices}
      choicesForValues={choicesForValues}
      recovered={recovery.data}
      returnTo={returnTo}
      reviewSource={reviewSource}
      checkSource={checkSource}
      renderContext={renderContext}
      canSubmit={canSubmit}
    />
  );
}

function CommandEditor({
  definition,
  sourceId,
  childId,
  revision,
  initial,
  choices,
  choicesForValues,
  recovered,
  returnTo,
  reviewSource,
  checkSource,
  renderContext,
  canSubmit,
}: {
  definition: Workflow;
  sourceId?: string;
  childId?: string;
  revision: number;
  initial: Record<string, unknown>;
  choices: Choices;
  choicesForValues?: (values: Record<string, unknown>) => Choices;
  recovered?: Recovery;
  returnTo?: string;
  reviewSource?: () => Promise<{
    revision: number;
    value: unknown;
    relatedRevisions?: Record<string, number>;
  }>;
  checkSource?: (values: Record<string, unknown>) => Promise<void>;
  canSubmit?: (values: Record<string, unknown>) => boolean;
  renderContext?: (
    values: Record<string, unknown>,
    locked: boolean,
    onChange: (values: Record<string, unknown>) => void,
  ) => ReactNode;
}) {
  const { scope } = useWorkspace();
  const location = useLocation();
  const [id] = useState(() => recovered?.id ?? crypto.randomUUID());
  const [error, setError] = useState<string>();
  const [review, setReview] = useState<{
    revision: number;
    value: unknown;
    spaceRevision?: number;
    relatedRevisions?: Record<string, number>;
  }>();
  const [attachment, setAttachment] = useState<File>();
  const [intakeFiles, setIntakeFiles] = useState<File[]>([]);
  const [selecting, setSelecting] = useState(false);
  const evidence =
    definition.formKey === "inspection.evidence.attach" || definition.formKey === "file.upload";
  const [removalConfirmed, setRemovalConfirmed] = useState(false);
  const requiresRemovalConfirmation =
    definition.formKey === "lease.participant.remove" ||
    (definition.formKey.startsWith("finance.") && definition.formKey.endsWith(".delete"));
  const [candidates, setCandidates] = useState<string[]>([]);
  const [receiptCandidates, setReceiptCandidates] = useState<string[]>([]);
  const [concernCandidates, setConcernCandidates] = useState<string[]>([]);
  const [expenseCandidates, setExpenseCandidates] = useState<Record<string, unknown>[]>([]);
  const revisionField =
    definition.sourceKind === "property" || definition.formKey === "portfolio.property.create"
      ? "expectedPropertyRevision"
      : definition.formKey.startsWith("lease.")
        ? "expectedLeaseRevision"
        : "expectedRevision";
  const project = useCallback(
    (values: { data: Record<string, unknown> }) =>
      toPayload(definition, record(clean(definition.schema, values.data)), childId),
    [definition, childId],
  );
  const { form, controller, state, blocker } = useRecoverableForm({
    id,
    identity: {
      formKey: definition.formKey,
      schemaVersion: 1,
      sourceKind: definition.sourceKind,
      sourceId: sourceId ?? null,
      baseSourceRevision: definition.sourceKind ? String(revision) : null,
    },
    initial: {
      data: recovered
        ? toBody(definition, recovered.payload, undefined, sourceId)
        : { ...initial, [revisionField]: revision },
    },
    recovered,
    project,
  });
  const values = useWatch({ control: form.control, name: "data" }) ?? {};
  const locked =
    state.command === "submitting" ||
    state.command === "outcome_unknown" ||
    state.command === "committed" ||
    state.draft === "conflicted";
  async function dispatch(saved: Recovery) {
    const key = saved.attemptKey;
    if (!key) throw new Error("Prepare the original command identity first.");
    return mutation<unknown>(async () => {
      if (definition.formKey === "intake.source.import") {
        const manifest = saved.payload.attachments as {
          role: "source_attachment" | "raw_source";
          contentSha256: string;
        }[];
        if (intakeFiles.length !== manifest.length)
          throw new Error("Reselect every original attachment in order.");
        for (const [index, file] of intakeFiles.entries()) {
          const metadata = await evidenceMetadata(file);
          if (metadata.contentSha256 !== manifest[index].contentSha256)
            throw new Error("Selected evidence does not match the saved attachment manifest.");
        }
        const { expectedRevision, attachments, ...metadata } = saved.payload;
        void expectedRevision;
        void attachments;
        const body = new FormData();
        body.append("metadata", JSON.stringify({ ...metadata, idempotencyKey: key }));
        body.append("attachmentRoles", JSON.stringify(manifest.map((entry) => entry.role)));
        for (const file of intakeFiles) body.append("files", file);
        return api.POST("/api/intake/sources/import", {
          body: { metadata: "", files: [] },
          bodySerializer: () => body,
        });
      }
      if (evidence) {
        if (!attachment) throw new Error("Reselect the original evidence before retrying.");
        const selected = await evidenceMetadata(attachment);
        for (const key of Object.keys(selected).filter(
          (key) => definition.formKey !== "file.upload" || key !== "sizeBytes",
        ))
          if (selected[key] !== saved.payload[key])
            throw new Error(
              "Selected evidence does not match the saved file. Reselect the original file.",
            );
        const body = new FormData();
        body.append("file", attachment);
        body.append("purpose", scalar(saved.payload.purpose));
        if (definition.formKey === "file.upload") {
          body.append("entity_type", scalar(saved.payload.entityType));
          body.append("entity_id", scalar(saved.payload.entityId));
          body.append("idempotency_key", key);
          return api.POST("/api/files", {
            body: {
              file: "",
              entity_type: scalar(saved.payload.entityType),
              entity_id: scalar(saved.payload.entityId),
              purpose: scalar(saved.payload.purpose),
              idempotency_key: key,
            },
            bodySerializer: () => body,
          });
        }
        body.append("expected_revision", scalar(saved.payload.expectedRevision));
        body.append("idempotency_key", key);
        return api.POST("/api/condition-observations/{observation_id}/evidence", {
          params: { path: { observation_id: sourceId! } },
          body: {
            file: "",
            purpose: saved.payload.purpose as "condition_photo" | "supporting_document",
            expected_revision: Number(saved.payload.expectedRevision),
            idempotency_key: key,
          },
          bodySerializer: () => body,
        });
      }
      const response = await dispatchWorkflow(
        definition.formKey,
        sourceId ?? "",
        scalar(saved.payload[definition.childKey ?? ""], childId),
        toBody(definition, saved.payload, key, sourceId),
      );
      const identifiers = record(record(response.error).detail).candidatePartyIds;
      const detail = record(record(response.error).detail);
      if (
        definition.formKey === "owner_concern.create" &&
        Array.isArray(detail.candidateConcernIds)
      )
        setConcernCandidates(
          detail.candidateConcernIds
            .filter((id): id is string => typeof id === "string")
            .slice(0, 20),
        );
      if (definition.formKey === "owner_rent_report.verify") {
        const ids = record(detail.details).candidateReceiptIds;
        if (Array.isArray(ids))
          setReceiptCandidates(
            ids.filter((id): id is string => typeof id === "string").slice(0, 10),
          );
      }
      if (
        definition.formKey === "finance.expense.create" &&
        detail.code === "possible_duplicate_expense" &&
        Array.isArray(detail.candidates)
      )
        setExpenseCandidates(detail.candidates.slice(0, 10).map(record));
      if (Array.isArray(identifiers))
        setCandidates(
          identifiers.filter((item): item is string => typeof item === "string").slice(0, 10),
        );
      return response;
    });
  }
  async function action(operation: () => Promise<unknown>) {
    setError(undefined);
    try {
      await operation();
      await scope.client.invalidateQueries({
        predicate: (query) =>
          query.queryKey[0] === scope.workspaceId &&
          !scalar(query.queryKey[2]).endsWith("command-source") &&
          query.queryKey[2] !== "workflow-recovery" &&
          query.queryKey[2] !== "recovery",
      });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Command failed.");
      await scope.client.invalidateQueries({
        predicate: (query) =>
          query.queryKey[0] === scope.workspaceId &&
          !scalar(query.queryKey[2]).endsWith("command-source") &&
          query.queryKey[2] !== "recovery" &&
          query.queryKey[2] !== "workflow-recovery",
      });
    }
  }
  async function readCurrent() {
    if (!sourceId) throw new Error("This command has no current source.");
    if (reviewSource) {
      setReview(await reviewSource());
      return;
    }
    switch (definition.sourceKind) {
      case "lease": {
        const lease = readResult(
          await api.GET("/api/leases/{lease_id}", { params: { path: { lease_id: sourceId } } }),
        );
        const space =
          "expectedRevision" in (definition.schema.properties ?? {})
            ? readResult(
                await api.GET("/api/spaces/{space_id}/status", {
                  params: { path: { space_id: lease.spaceId } },
                }),
              )
            : undefined;
        setReview({ revision: lease.leaseRevision, value: lease, spaceRevision: space?.revision });
        break;
      }
      case "property": {
        const item = readResult(
          await api.GET("/api/properties/{property_id}", {
            params: { path: { property_id: sourceId } },
          }),
        );
        setReview({ revision: item.propertyRevision, value: item });
        break;
      }
      case "space": {
        const item = readResult(
          await api.GET("/api/spaces/{space_id}/status", {
            params: { path: { space_id: sourceId } },
          }),
        );
        setReview({ revision: item.revision, value: item });
        break;
      }
      case "party": {
        const item = readResult(
          await api.GET("/api/parties/{party_id}", { params: { path: { party_id: sourceId } } }),
        );
        setReview({ revision: item.revision, value: item });
        break;
      }
      case "tenant": {
        const item = readResult(
          await api.GET("/api/tenants/{party_id}", { params: { path: { party_id: sourceId } } }),
        );
        setReview({ revision: item.profile.revision, value: item.profile });
        break;
      }
      case "provider": {
        const item = readResult(
          await api.GET("/api/providers/{party_id}", { params: { path: { party_id: sourceId } } }),
        );
        setReview({ revision: item.profile.revision, value: item.profile });
        break;
      }
      case "provider_category": {
        const items = readResult(
          await api.GET("/api/provider-categories", { params: { query: { archiveState: "all" } } }),
        );
        const item = items.find((value) => value.id === sourceId);
        if (!item) throw new Error("Category unavailable.");
        setReview({ revision: item.revision, value: item });
        break;
      }
    }
  }
  const back =
    typeof record(location.state).returnTo === "string"
      ? String(record(location.state).returnTo)
      : (returnTo ??
        (definition.sourceKind === "property"
          ? `/properties/${sourceId}/setup`
          : definition.sourceKind === "space"
            ? `/properties?space=${sourceId}`
            : definition.sourceKind === "provider"
              ? `/providers/${sourceId}/details`
              : definition.sourceKind === "party" || definition.sourceKind === "tenant"
                ? `/parties?identity=${sourceId}`
                : `/${definition.formKey.startsWith("provider.") ? "providers" : definition.formKey.startsWith("lease.") || definition.formKey.startsWith("inspection.") ? "leasing" : "properties"}`));
  const commandStatus = (
    <>
      <p>
        Displayed source revision: {scalar(values[revisionField], String(revision))}. This command
        retains its original revision and attempt identity.
      </p>
      <p role="status">
        Draft {state.draft} · Command {state.command}
      </p>
    </>
  );
  return (
    <section aria-label={definition.title} className="command-editor">
      <h2>{definition.title}</h2>
      <p>
        {definition.formKey === "portfolio.property.create"
          ? "Start with the property name and address, choose its rental layout, and confirm the owners. Occupancy, leasing status and lease records can be added afterward."
          : definition.formKey === "portfolio.space.classify"
            ? "Add occupancy, leasing status, or both below. Save to apply your changes; saving an unfinished form does not update the property’s records."
            : definition.formKey === "portfolio.availability.change"
              ? "Choose whether the property is not open for leasing, open now, or open from a future date. For a future opening, enter the date. Add an optional note, then save."
              : definition.formKey === "portfolio.occupancy.change"
                ? "Choose the new occupancy status and when it takes effect in the property’s time zone. A future date schedules the change; it does not change today’s occupancy. Add an optional note, then save."
                : ["portfolio.space.patch", "portfolio.property.patch"].includes(definition.formKey)
                  ? "Edit the details below, then save your changes. Saving an unfinished form does not update the property’s records."
                  : definition.formKey === "portfolio.space.archive"
                    ? "Confirm that you want to archive this rental, then select Archive below. Saving an unfinished form does not archive it."
                    : "Review the displayed record and make an explicit change. Saved input is an unfinished form, not an official record."}
      </p>
      {[
        "portfolio.space.classify",
        "portfolio.availability.change",
        "portfolio.occupancy.change",
        "portfolio.space.patch",
        "portfolio.space.archive",
        "portfolio.property.patch",
        "portfolio.property.create",
      ].includes(definition.formKey) ? (
        <details className="space-classification-recovery">
          <summary>Form status and recovery details</summary>
          {commandStatus}
        </details>
      ) : (
        commandStatus
      )}
      {(error ?? state.error) && <p role="alert">{error ?? state.error}</p>}
      {candidates.length > 0 && (
        <section aria-label="Possible duplicate identities">
          <h3>Review possible duplicate identities</h3>
          <p>
            The server has not confirmed a new record. Review these shared identities before
            deciding whether a separate identity is needed.
          </p>
          {candidates.map((candidate) => (
            <p key={candidate}>
              <Link to={`/parties?identity=${candidate}`}>Review identity {candidate}</Link>
            </p>
          ))}
        </section>
      )}
      {receiptCandidates.length > 0 && (
        <section aria-label="Possible duplicate rent receipts">
          <h3>Review existing rent receipts</h3>
          <p>
            No new income was recorded. Review the matching receipt and explicitly choose adoption;
            there is no independent-payment override for Owner reports.
          </p>
          {receiptCandidates.map((id) => (
            <p key={id}>
              <Link to={`/money?record=receipt&id=${id}`}>Review existing receipt {id}</Link>
            </p>
          ))}
          <Link
            to={`/money?workflow=owner_rent_report.verify&target=${sourceId}&receiptMode=existing`}
          >
            Start explicit adoption review
          </Link>
        </section>
      )}
      {concernCandidates.length > 0 && (
        <section aria-label="Possible duplicate concerns">
          <h3>Review existing Owner concerns</h3>
          <p>
            No concern was merged or created. Review the candidates, then start a separate
            independent-concern review with explicit confirmation and a reason. The original attempt
            remains retained for recovery.
          </p>
          {concernCandidates.map((id) => (
            <p key={id}>
              <Link to={`/maintenance?record=concern&id=${id}`}>Review existing concern {id}</Link>
            </p>
          ))}
          <Link
            state={{ concernReview: values }}
            to="/maintenance?workflow=owner_concern.create&independentReview=true"
          >
            Start independent concern review
          </Link>
        </section>
      )}
      {state.problem && (
        <ul>
          {Object.entries(state.problem.fieldErrors).map(([name, errors]) => (
            <li key={name}>
              {name}: {errors.join(" ")}
            </li>
          ))}
        </ul>
      )}
      {expenseCandidates.length > 0 && (
        <section aria-label="Possible duplicate expenses">
          <h3>Review possible duplicate expenses</h3>
          <p>
            No new expense has been recorded. Review the existing spending before recording a
            separate payment.
          </p>
          {expenseCandidates.map((candidate) => (
            <article key={scalar(candidate.id)}>
              <MoneyFacts
                value={candidate}
                fields={["paidOn", "amount", "payeeName", "description"]}
              />
              <Link to={`/money?record=expense&id=${encodeURIComponent(scalar(candidate.id))}`}>
                Open existing expense
              </Link>
            </article>
          ))}
          <Link to={returnTo ?? "/money?tab=expenses"}>Go back</Link>
          <p>
            The original submitted payload remains locked. Do not change or resend an unresolved
            attempt.
          </p>
        </section>
      )}
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void action(async () => {
            if (evidence && !attachment)
              throw new Error("Select the evidence file before submitting.");
            if (requiresRemovalConfirmation && !removalConfirmed)
              throw new Error("Confirm removal of this Lease participant.");
            validateRequest(definition.schema, {
              ...record(clean(definition.schema, values)),
              idempotencyKey: crypto.randomUUID(),
            });
            if (checkSource)
              await checkSource({
                ...values,
                ...(definition.childKey && childId ? { [definition.childKey]: childId } : {}),
              });
            await controller.submit(dispatch);
          });
        }}
      >
        <fieldset disabled={locked || !scope.canWrite}>
          <legend>Requested change</legend>
          {requiresRemovalConfirmation && (
            <label>
              <input
                type="checkbox"
                checked={removalConfirmed}
                onChange={(event) => setRemovalConfirmed(event.target.checked)}
              />
              {definition.formKey === "lease.participant.remove"
                ? "I confirm removal of this Lease participant"
                : "I confirm deletion of this draft settlement child"}
            </label>
          )}
          {evidence && (
            <>
              <p>
                Files are never saved in unfinished forms. After restart, reselect the original
                file; its name, size and SHA-256 must match before replay.
              </p>
              <label>
                Evidence file (required)
                <input
                  type="file"
                  disabled={selecting}
                  onChange={(event) => {
                    const file = event.target.files?.[0];
                    setAttachment(undefined);
                    if (!file) return;
                    setSelecting(true);
                    void evidenceMetadata(file)
                      .then((metadata) => {
                        if (
                          recovered &&
                          Object.entries(metadata).some(
                            ([key, value]) =>
                              (definition.formKey !== "file.upload" || key !== "sizeBytes") &&
                              recovered.payload[key] !== value,
                          )
                        )
                          throw new Error("Selected evidence does not match the saved file.");
                        form.setValue("data", { ...form.getValues("data"), ...metadata });
                        setAttachment(file);
                        setError(undefined);
                      })
                      .catch((cause: unknown) =>
                        setError(
                          cause instanceof Error ? cause.message : "Could not read evidence.",
                        ),
                      )
                      .finally(() => setSelecting(false));
                  }}
                />
              </label>
              <Facts
                value={values}
                fields={["originalName", "mediaType", "sizeBytes", "contentSha256"]}
              />
            </>
          )}
          {definition.formKey === "intake.source.import" && (
            <>
              <p>
                Files are not saved in unfinished forms. Reselect the original bytes in the same
                order after restart. Choose the role for each attachment below.
              </p>
              <label>
                Source attachment files
                <input
                  type="file"
                  multiple
                  disabled={selecting}
                  onChange={(event) => {
                    const selected = Array.from(event.target.files ?? []);
                    setIntakeFiles([]);
                    if (
                      selected.length > 20 ||
                      selected.some((file) => file.size > 50 * 1024 * 1024) ||
                      selected.reduce((sum, file) => sum + file.size, 0) > 100 * 1024 * 1024
                    ) {
                      setError(
                        "Select at most 20 files, each at most 50 MiB, totaling at most 100 MiB.",
                      );
                      return;
                    }
                    setSelecting(true);
                    void Promise.all(selected.map(evidenceMetadata))
                      .then((metadata) => {
                        if (
                          selected.length > 20 ||
                          selected.reduce((sum, file) => sum + file.size, 0) > 100 * 1024 * 1024
                        )
                          throw new Error("Select at most 20 files totaling at most 100 MiB.");
                        const previous = (form.getValues("data").attachments ?? []) as {
                          role: string;
                          contentSha256: string;
                        }[];
                        if (
                          recovered &&
                          (previous.length !== metadata.length ||
                            previous.some(
                              (entry, index) =>
                                entry.contentSha256 !== metadata[index].contentSha256,
                            ))
                        )
                          throw new Error(
                            "Selected evidence does not match the saved attachment manifest.",
                          );
                        form.setValue("data", {
                          ...form.getValues("data"),
                          attachments: metadata.map((item, index) => ({
                            role: previous[index]?.role ?? "source_attachment",
                            contentSha256: item.contentSha256,
                          })),
                        });
                        setIntakeFiles(selected);
                        setError(undefined);
                      })
                      .catch((cause: unknown) =>
                        setError(
                          cause instanceof Error
                            ? cause.message
                            : "Could not read source attachments.",
                        ),
                      )
                      .finally(() => setSelecting(false));
                  }}
                />
              </label>
              {(Array.isArray(values.attachments) ? values.attachments : []).map((entry, index) => (
                <label key={index}>
                  Attachment {index + 1} role
                  <select
                    value={scalar(record(entry).role)}
                    onChange={(event) => {
                      const attachments = [...(values.attachments as Record<string, unknown>[])];
                      attachments[index] = { ...record(entry), role: event.target.value };
                      form.setValue("data", { ...values, attachments });
                    }}
                  >
                    <option value="source_attachment">Source attachment</option>
                    <option value="raw_source">Raw source</option>
                  </select>
                  <span>{scalar(record(entry).contentSha256)}</span>
                </label>
              ))}
            </>
          )}
          {definition.formKey === "task.create" ? (
            <TaskCreateFields
              schema={definition.schema}
              value={values}
              onChange={(next) => form.setValue("data", next)}
              choices={choicesForValues?.(values) ?? choices}
              disabled={locked}
            />
          ) : definition.formKey === "portfolio.property.create" ? (
            <PropertyCreateFields
              schema={definition.schema}
              value={values}
              onChange={(next) => form.setValue("data", next)}
              choices={choicesForValues?.(values) ?? choices}
              disabled={locked}
            />
          ) : definition.formKey === "portfolio.property.patch" ? (
            <PropertyEditFields
              schema={definition.schema}
              value={values}
              onChange={(next) => form.setValue("data", next)}
              disabled={locked}
            />
          ) : (
            <Fields
              schema={
                evidence
                  ? {
                      ...definition.schema,
                      properties: { purpose: definition.schema.properties!.purpose },
                    }
                  : definition.formKey.startsWith("intake.")
                    ? {
                        ...definition.schema,
                        properties: Object.fromEntries(
                          Object.entries(definition.schema.properties ?? {}).filter(
                            ([key]) =>
                              ![
                                "expectedEvidenceRevisionId",
                                "expectedStatus",
                                "attachments",
                              ].includes(key),
                          ),
                        ),
                      }
                    : definition.schema
              }
              value={values}
              onChange={(next) => form.setValue("data", record(next))}
              choices={choicesForValues?.(values) ?? choices}
              disabled={locked}
            />
          )}
        </fieldset>
        {renderContext?.(values, locked, (next) => form.setValue("data", next))}
        {!locked && (
          <>
            <button
              type="submit"
              disabled={!scope.canWrite || selecting || canSubmit?.(values) === false}
            >
              {["portfolio.space.archive", "portfolio.property.create"].includes(definition.formKey)
                ? definition.title
                : `Save ${definition.title.toLowerCase()}`}
            </button>
            <button
              type="button"
              onClick={() => {
                void action(() => controller.flush());
              }}
            >
              Save unfinished form
            </button>
          </>
        )}
      </form>
      {state.command === "outcome_unknown" && (
        <>
          <p>The outcome is unresolved. Check the original receipt before continuing.</p>
          <button
            onClick={() => {
              void action(() => controller.reconcile());
            }}
          >
            Check original result
          </button>
          <button
            onClick={() => {
              void action(() => controller.replay(dispatch));
            }}
          >
            Retry original attempt
          </button>
        </>
      )}
      {state.draft === "failed" && !locked && (
        <button
          onClick={() => {
            void action(() => controller.flush());
          }}
        >
          Retry saving input
        </button>
      )}
      {state.draft === "conflicted" && (
        <p>
          Your input is retained. Return to the current record to review its latest revision before
          starting a new command.
        </p>
      )}
      {definition.sourceKind &&
        state.command !== "outcome_unknown" &&
        state.command !== "committed" &&
        state.command !== "submitting" && (
          <button
            onClick={() => {
              void action(readCurrent);
            }}
          >
            Review current source
          </button>
        )}
      {review && (
        <section aria-label="Current source review">
          <h3>Current source revision {review.revision}</h3>
          {definition.formKey.startsWith("intake.") && (
            <>
              <Facts
                value={review.value}
                fields={[
                  "sourceRevision",
                  "evidenceRevisionId",
                  "technicalStatus",
                  "attentionStatus",
                ]}
              />
              <Facts
                value={record(review.value).evidence}
                fields={["subject", "body", "occurredAtContext"]}
              />
            </>
          )}
          <Facts
            value={review.value}
            fields={[
              "displayName",
              "status",
              "archivedAt",
              "updatedAt",
              "selectionStatus",
              "notes",
            ]}
          />
          <p>
            Your requested business fields remain unchanged. Only the concurrency revision will
            change after you confirm this review.
          </p>
          <button
            onClick={() => {
              void action(async () => {
                const response = await api.GET("/api/operator/recovery/{record_id}", {
                  params: { path: { record_id: id } },
                });
                if (!response.data && response.response.status !== 404)
                  throw new Error("Could not check the saved form.");
                controller.reviewSource(
                  response.data,
                  review.revision,
                  definition.formKey.startsWith("lease.") ? "expectedRevision" : revisionField,
                );
                form.setValue("data", {
                  ...values,
                  [revisionField]: review.revision,
                  ...(definition.formKey.startsWith("intake.")
                    ? {
                        expectedEvidenceRevisionId: record(review.value).evidenceRevisionId,
                        expectedStatus: record(review.value).attentionStatus,
                      }
                    : {}),
                  ...review.relatedRevisions,
                  ...(review.spaceRevision === undefined
                    ? {}
                    : { expectedRevision: review.spaceRevision }),
                });
                await controller.flush();
                setReview(undefined);
              });
            }}
          >
            Keep my edits with this reviewed revision
          </button>
        </section>
      )}
      {state.record?.receipt && (
        <section aria-label="Committed result">
          <h3>Committed result</h3>
          <p>Operation {state.record.receipt.receiptId}</p>
          <FactsResult value={state.record.receipt.result} />
          {definition.formKey.startsWith("intake.") && state.record.attemptKey && (
            <OriginalIntakeResult attemptKey={state.record.attemptKey} />
          )}
          {(definition.formKey.startsWith("task.") ||
            definition.formKey.startsWith("communication.") ||
            definition.formKey.startsWith("maintenance.") ||
            definition.formKey.startsWith("owner_concern.")) &&
            state.record.attemptKey && (
              <OriginalWorkResult
                definition={definition}
                attemptKey={state.record.attemptKey}
                operationId={state.record.receipt.receiptId}
                sourceId={sourceId}
              />
            )}
          {(definition.formKey.startsWith("lease.") ||
            definition.formKey.startsWith("inspection.")) && (
            <OriginalWorkflowResult
              family={definition.formKey.startsWith("lease.") ? "lease" : "inspection"}
              operationId={state.record.receipt.receiptId}
            />
          )}
          {(definition.formKey.startsWith("finance.") ||
            definition.formKey.startsWith("owner_rent_report.") ||
            definition.formKey === "file.upload") &&
            state.record.attemptKey && (
              <OriginalMoneyResult
                definition={definition}
                attemptKey={state.record.attemptKey}
                sourceId={sourceId}
              />
            )}
        </section>
      )}
      <Link to={back}>Return to current record</Link>
      <RecoveryNavigation controller={controller} blocker={blocker} />
    </section>
  );
}

function OriginalIntakeResult({ attemptKey }: { attemptKey: string }) {
  const { scope } = useWorkspace();
  const result = useQuery({
    queryKey: scope.key("original-intake-result", attemptKey),
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/intake/sources/operations/by-key/{idempotency_key}", {
          signal,
          params: { path: { idempotency_key: attemptKey } },
        }),
      ),
    retry: false,
  });
  return (
    <>
      {result.isPending && <p role="status">Loading original source receipt…</p>}
      {result.error && (
        <p role="alert">
          The command committed, but its original receipt is unavailable: {result.error.message}
        </p>
      )}
      {result.data && (
        <>
          <Facts
            value={result.data}
            fields={[
              "sourceId",
              "technicalStatus",
              "attentionStatus",
              "sourceRevision",
              "operationId",
            ]}
          />
          <p>This is the original committed response.</p>
          <Link to={`/conversations?intake=true&source=${result.data.sourceId}`}>
            Open current source evidence
          </Link>
        </>
      )}
    </>
  );
}

function OriginalMoneyResult({
  definition,
  attemptKey,
  sourceId,
}: {
  definition: Workflow;
  attemptKey: string;
  sourceId?: string;
}) {
  const { scope } = useWorkspace();
  const result = useQuery({
    queryKey: scope.key("original-money-result", definition.formKey, attemptKey),
    queryFn: async ({ signal }) => {
      if (definition.formKey === "file.upload")
        return readResult(
          await api.GET("/api/files/commands/by-key/{key}", {
            signal,
            params: { path: { key: attemptKey } },
          }),
        );
      if (definition.formKey.startsWith("owner_rent_report."))
        return readResult(
          await api.GET("/api/owner-rent-report-operations/{key}", {
            signal,
            params: { path: { key: attemptKey } },
          }),
        ).result;
      if (definition.formKey.startsWith("finance.expense_category."))
        return readResult(
          await api.GET("/api/expense-categories/operations/by-key/{key}", {
            signal,
            params: { path: { key: attemptKey } },
          }),
        );
      return readResult(
        await api.GET("/api/finance/command-operations/{idempotency_key}", {
          signal,
          params: { path: { idempotency_key: attemptKey } },
        }),
      ).result;
    },
  });
  const item = record(result.data);
  const kind = definition.formKey.startsWith("owner_rent_report.")
    ? "report"
    : definition.formKey.startsWith("finance.expense_category.")
      ? "category"
      : definition.formKey.startsWith("finance.expense_refund.")
        ? "expense"
        : definition.formKey.startsWith("finance.expense.")
          ? "expense"
          : definition.formKey.startsWith("finance.prepaid_check.")
            ? "check"
            : definition.formKey.startsWith("finance.rent_receipt.")
              ? "receipt"
              : definition.formKey.startsWith("finance.rent_expectation.")
                ? "expectation"
                : "deposit";
  return (
    <>
      {result.isPending && <p role="status">Loading original money receipt…</p>}
      {result.error && (
        <p role="alert">
          The money operation is committed; its detailed receipt is unavailable:{" "}
          {result.error.message}
        </p>
      )}
      {result.data && (
        <>
          <MoneyFacts
            value={item}
            fields={[
              "id",
              "status",
              "amount",
              "amountMinor",
              "receivedOn",
              "paidOn",
              "paymentMethodKind",
              "refundDue",
              "voidReason",
              "operationId",
              "rentLedgerRevision",
              "expenseRevision",
              "depositAccountRevision",
              "reportRevision",
              "updatedAt",
            ]}
          />
          {Array.isArray(item.items) &&
            (item.items as unknown[]).map((entry) => (
              <MoneyFacts
                key={scalar(record(entry).id)}
                value={entry}
                fields={[
                  "id",
                  "dueOn",
                  "periodStartsOn",
                  "periodEndsOn",
                  "expectedAmountMinor",
                  "outstandingAmountMinor",
                  "lifecycleStatus",
                ]}
              />
            ))}
          {Array.isArray(item.allocations) &&
            (item.allocations as unknown[]).map((entry) => (
              <MoneyFacts
                key={scalar(record(entry).id)}
                value={entry}
                fields={["expectationId", "amountMinor", "expectationDueOn"]}
              />
            ))}
          <p>This is the original committed response.</p>
          {(item.id || item.expenseId || item.accountId) && (
            <>
              {definition.formKey === "finance.expense.create" && item.id && (
                <p>
                  Expense saved. Add evidence now or keep the saved expense without attachments.{" "}
                  <Link
                    to={`/money?workflow=file.upload&entityType=expense&entityId=${scalar(item.id)}&purpose=receipt`}
                  >
                    Add expense evidence
                  </Link>{" "}
                  <Link to={`/money?record=expense&id=${scalar(item.id)}`}>
                    Skip evidence and review saved expense
                  </Link>
                </p>
              )}
              <Link
                to={
                  definition.formKey === "file.upload"
                    ? `/money?file=${scalar(item.id)}`
                    : `/money?record=${kind}&id=${scalar(item.expenseId ?? (kind === "deposit" ? (sourceId ?? item.accountId ?? item.id) : item.id))}`
                }
              >
                Open current money record
              </Link>
            </>
          )}
        </>
      )}
    </>
  );
}

function OriginalWorkflowResult({
  family,
  operationId,
}: {
  family: "lease" | "inspection";
  operationId: string;
}) {
  const { scope } = useWorkspace();
  const result = useQuery({
    queryKey: scope.key("original-workflow-result", family, operationId),
    queryFn: async ({ signal }) => {
      if (family === "lease")
        return readResult(
          await api.GET("/api/leases/operations/{operation_id}", {
            signal,
            params: { path: { operation_id: operationId } },
          }),
        ).response;
      return readResult(
        await api.GET("/api/inspection-commands/{operation_id}", {
          signal,
          params: { path: { operation_id: operationId } },
        }),
      ).result;
    },
  });
  return (
    <>
      {result.isPending && <p role="status">Loading original committed snapshot…</p>}
      {result.error && (
        <p role="alert">
          The primary result is committed. Its detailed receipt is unavailable:{" "}
          {result.error.message}
        </p>
      )}
      {result.data && (
        <>
          <Facts
            value={result.data}
            fields={["id", "status", "leaseRevision", "revision", "updatedAt", "operationId"]}
          />
          {family === "lease" && "spaceId" in result.data && (
            <Link to={`/leases/${result.data.id}/details`}>
              Open committed Lease and related setup
            </Link>
          )}
          {family === "inspection" && "leaseId" in result.data && (
            <Link to={`/inspections/${result.data.id}`}>Open committed inspection</Link>
          )}
        </>
      )}
    </>
  );
}

async function evidenceMetadata(file: File): Promise<Record<string, unknown>> {
  if (file.size === 0 || file.size > 50 * 1024 * 1024)
    throw new Error("Evidence must contain 1 byte to 50 MiB.");
  const originalName = file.name.normalize("NFC").trim();
  if (
    !originalName ||
    [".", ".."].includes(originalName) ||
    /[/\\\p{Cc}]/u.test(originalName) ||
    new TextEncoder().encode(originalName).length > 255
  )
    throw new Error("Evidence needs a safe display filename of at most 255 UTF-8 bytes.");
  const declaredType = file.type.trim().toLowerCase();
  const mediaType =
    /^[a-z0-9!#$&^_.+-]+\/[a-z0-9!#$&^_.+-]+(?:;[a-z0-9!#$&^_.+-]+=[a-z0-9!#$&^_.+-]+)*$/.test(
      declaredType,
    )
      ? declaredType
      : "application/octet-stream";
  const hash = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  return {
    originalName,
    mediaType,
    sizeBytes: file.size,
    contentSha256: Array.from(new Uint8Array(hash), (value) =>
      value.toString(16).padStart(2, "0"),
    ).join(""),
  };
}

function FactsResult({ value }: { value: unknown }) {
  const result = record(value);
  return (
    <p>
      Result record {scalar(result.targetId ?? result.resultId ?? result.id, "see owning receipt")}{" "}
      · Revision {scalar(result.revision ?? result.resultingRevision, "see owning receipt")} ·{" "}
      {scalar(result.status, "committed")}
    </p>
  );
}
