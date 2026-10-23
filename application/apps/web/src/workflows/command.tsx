import { useCallback, useState, type ReactNode } from "react";
import { useWatch } from "react-hook-form";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import {
  ParentBackLink,
  SourceWorkflowLink as Link,
  useSourceNavigationState,
} from "../shared/home-navigation";
import { api } from "@epm/contracts";
import {
  workflows,
  dispatchWorkflow,
  record,
  scalar,
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
import { TaskCreateFields } from "./task-fields";
import { MaintenanceCreateFields } from "./maintenance-create-fields";
import { GroupedCommandFields } from "./grouped-command-fields";
import { WorkCommandFields, hasWorkCommandFields } from "./work-command-fields";
import { AppointmentFields } from "./appointment-fields";
import { PropertyEditFields } from "./property-edit-fields";
import { PropertyCreateFields } from "./property-create-fields";
import { OwnershipFields } from "./ownership-fields";
import { ownershipShareProblem } from "../shared/ownership-shares";
import { SavedCommand } from "./saved-command";
import { FormFeedback, fieldName, validateForm } from "./form-feedback";
import { DraftSaveStatus, draftSaveLabel } from "../shared/draft-save-status";

const workflowIntroductions: Partial<Record<Workflow["formKey"], string>> = {
  "maintenance.issue.start": "Mark this issue as In progress when work is being handled.",
  "maintenance.issue.resolve":
    "Review the issue and describe its resolution. Scheduled appointments must be completed or cancelled first.",
  "maintenance.issue.cancel":
    "Record why the issue no longer needs to be handled. Its history will be retained.",
  "maintenance.appointment.create":
    "Schedule a visit for this issue and add any access instructions.",
  "maintenance.quote.create":
    "Record a provider's offer so you can compare its scope, price and proposed dates.",
  "maintenance.assignment.create":
    "Select the provider handling this issue and record why you chose them.",
  "maintenance.cost.create":
    "Record an estimate or reported cost. Record actual spending separately as a paid expense.",
  "maintenance.expense.link":
    "Associate an existing paid expense with this issue without recording it twice.",
  "maintenance.follow_up.create": "Create a task to track the next step for this issue.",
  "maintenance.journal.record":
    "Record what happened, who reported it, and whether completed work was verified.",
  "maintenance.quote.withdraw":
    "Withdraw an offer that is no longer valid. The original remains in history.",
  "communication.create":
    "Record a conversation that happened outside the app, or save it as a draft. Nothing is sent.",
  "maintenance.issue.patch":
    "Update issue details and reporter information together. A reporter change requires a correction reason. The property and issue status stay unchanged.",
  "finance.expense_category.create":
    "Add a category for grouping paid expenses. No spending is recorded by creating a category.",
  "finance.expense_category.patch":
    "Update this expense category. Existing expenses keep their recorded amounts and history.",
  "finance.rent_receipt.create":
    "Record money already received, how it was paid, and the rent periods it covers. Review the totals before saving.",
};

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
                : formKey.startsWith("tenant.")
                  ? "tenants"
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
  dropdown = false,
}: {
  keys: string[];
  target?: string;
  child?: string;
  title?: string;
  labels?: Record<string, string>;
  collapsible?: boolean;
  asButtons?: boolean;
  dropdown?: boolean;
}) {
  const { scope } = useWorkspace();
  const location = useLocation();
  const navigate = useNavigate();
  const navigationState = useSourceNavigationState();
  if (!scope.canWrite) return <p>Workspace writes are unavailable.</p>;
  if (dropdown)
    return (
      <label className="workflow-action-select">
        {title}
        <select
          value=""
          onChange={(event) => {
            const url = workflowUrl(event.target.value, target, child);
            void navigate(url, {
              state: navigationState({ returnTo: location.pathname + location.search }, url),
            });
          }}
        >
          <option value="" disabled>
            Choose an action…
          </option>
          {keys.map((key) => {
            const item = workflows.find((entry) => entry.formKey === key);
            return item ? (
              <option key={key} value={key}>
                {labels[key] ?? item.title}
              </option>
            ) : null;
          })}
        </select>
      </label>
    );
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
                  state: navigationState(
                    { returnTo: location.pathname + location.search },
                    workflowUrl(key, target, child),
                  ),
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

type CommandHostBaseProps = {
  definition: Workflow;
  propertyTimeZone?: string;
  sourceId?: string;
  childId?: string;
  revision: number;
  choicesForValues?: (values: Record<string, unknown>) => Choices;
  returnTo?: string;
  onSaved?: () => void;
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
  renderFields?: (
    values: Record<string, unknown>,
    locked: boolean,
    onChange: (values: Record<string, unknown>) => void,
  ) => ReactNode;
};

type CommandLoaderProps = CommandHostBaseProps & {
  initial?: Record<string, unknown>;
  choices?: Choices;
  showParentLink?: boolean;
  embedded?: boolean;
};

type CommandEditorProps = CommandHostBaseProps & {
  initial: Record<string, unknown>;
  choices: Choices;
  recovered?: Recovery;
  showParentLink: boolean;
  embedded: boolean;
};

export function CommandLoader({
  definition,
  propertyTimeZone,
  sourceId,
  childId,
  revision,
  initial = {},
  choices = {},
  choicesForValues,
  returnTo,
  showParentLink = true,
  embedded = false,
  onSaved,
  reviewSource,
  checkSource,
  renderContext,
  renderFields,
  canSubmit,
}: CommandLoaderProps) {
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
      propertyTimeZone={propertyTimeZone}
      sourceId={sourceId}
      childId={selectedChild}
      revision={revision}
      initial={initial}
      choices={choices}
      choicesForValues={choicesForValues}
      recovered={recovery.data}
      returnTo={returnTo}
      showParentLink={showParentLink}
      embedded={embedded}
      onSaved={onSaved}
      reviewSource={reviewSource}
      checkSource={checkSource}
      renderContext={renderContext}
      renderFields={renderFields}
      canSubmit={canSubmit}
    />
  );
}

function CommandEditor({
  definition,
  propertyTimeZone,
  sourceId,
  childId,
  revision,
  initial,
  choices,
  choicesForValues,
  recovered,
  returnTo,
  showParentLink,
  embedded,
  onSaved,
  reviewSource,
  checkSource,
  renderContext,
  renderFields,
  canSubmit,
}: CommandEditorProps) {
  const { scope } = useWorkspace();
  const location = useLocation();
  const addingContact = definition.formKey === "party.contact.add";
  const editingContact = definition.formKey === "party.contact.update";
  const removingContact = definition.formKey === "party.contact.archive";
  const personEdit =
    definition.formKey === "party.patch" || addingContact || editingContact || removingContact;
  const hasContextNavigation =
    [
      "portfolio.ownerships.replace",
      "portfolio.property.patch",
      "portfolio.space.patch",
      "portfolio.property.create",
      "portfolio.space.archive",
      "portfolio.space.classify",
      "portfolio.availability.change",
      "portfolio.occupancy.change",
    ].includes(definition.formKey) || personEdit;
  const commandTitle = addingContact
    ? "Add contact details"
    : editingContact
      ? "Edit contact details"
      : removingContact
        ? "Remove contact details"
        : definition.formKey === "party.patch"
          ? "Edit name and identity"
          : definition.title;
  const editSubject = /^Edit (.+)$/i.exec(commandTitle)?.[1];
  const correctionSubject = /^Correct (.+)$/i.exec(commandTitle)?.[1];
  const createsRecord =
    /\.(create|add|record|admit|import|attach|upload|assign|designate|link)$/.test(
      definition.formKey,
    );
  const [id] = useState(() => recovered?.id ?? crypto.randomUUID());
  const [error, setError] = useState<string>();
  const [sourceCheckFailed, setSourceCheckFailed] = useState(false);
  const [feedbackAttempt, setFeedbackAttempt] = useState(0);
  const [review, setReview] = useState<{
    revision: number;
    value: unknown;
    spaceRevision?: number;
    relatedRevisions?: Record<string, number>;
  }>();
  const [attachment, setAttachment] = useState<File>();
  const [intakeFiles, setIntakeFiles] = useState<File[]>([]);
  const [selecting, setSelecting] = useState(false);
  const [addingOwner, setAddingOwner] = useState(false);
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
  const { form, controller, state, blocker } = useRecoverableForm<{
    data: Record<string, unknown>;
  }>({
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
        ? {
            ...(definition.formKey === "portfolio.property.create" ? { countryCode: "US" } : {}),
            ...toBody(definition, recovered.payload, undefined, sourceId),
          }
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
          query.queryKey[2] !== "saved-command" &&
          query.queryKey[2] !== "workflow-recovery" &&
          query.queryKey[2] !== "recovery",
      });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Command failed.");
      setFeedbackAttempt((attempt) => attempt + 1);
      await scope.client.invalidateQueries({
        predicate: (query) =>
          query.queryKey[0] === scope.workspaceId &&
          !scalar(query.queryKey[2]).endsWith("command-source") &&
          query.queryKey[2] !== "saved-command" &&
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
              : definition.sourceKind === "tenant"
                ? `/tenants?identity=${sourceId}`
                : definition.sourceKind === "party"
                  ? `/parties?identity=${sourceId}`
                  : `/${definition.formKey.startsWith("provider.") ? "providers" : definition.formKey.startsWith("lease.") || definition.formKey.startsWith("inspection.") ? "leasing" : "properties"}`));
  const currentSourceAction =
    definition.sourceKind &&
    state.command !== "outcome_unknown" &&
    state.command !== "committed" &&
    state.command !== "submitting" ? (
      <button
        type="button"
        onClick={() => {
          void action(readCurrent);
        }}
      >
        {personEdit
          ? "Check latest contact record"
          : definition.formKey === "portfolio.ownerships.replace"
            ? "Check latest property record"
            : "Review current source"}
      </button>
    ) : null;
  const saveActions = (
    <>
      <button
        type="submit"
        disabled={!scope.canWrite || selecting || addingOwner || canSubmit?.(values) === false}
      >
        {definition.formKey === "maintenance.issue.patch"
          ? "Save issue changes"
          : definition.formKey === "maintenance.issue.start"
            ? "Start work"
            : definition.formKey === "maintenance.issue.resolve"
              ? "Resolve issue"
              : definition.formKey === "maintenance.issue.cancel"
                ? "Cancel issue"
                : definition.formKey === "maintenance.quote.withdraw"
                  ? "Withdraw quote"
                  : createsRecord || definition.formKey === "portfolio.space.archive"
                    ? commandTitle
                    : editingContact
                      ? "Save contact details"
                      : removingContact
                        ? "Remove contact details"
                        : definition.formKey === "party.patch"
                          ? "Save name and identity"
                          : definition.formKey === "portfolio.ownerships.replace"
                            ? "Save ownership change"
                            : editSubject
                              ? `Save ${editSubject.toLowerCase()} changes`
                              : correctionSubject
                                ? `Save ${correctionSubject.toLowerCase()} correction`
                                : `Save ${definition.title.toLowerCase()}`}
      </button>
      <button
        type="button"
        disabled={addingOwner || state.draft === "saved" || state.draft === "saving"}
        onClick={() => {
          void action(() => controller.flush());
        }}
      >
        {draftSaveLabel(state.draft)}
      </button>
    </>
  );
  if (state.command === "committed" && state.record?.receipt)
    return (
      <SavedCommand
        definition={definition}
        recovery={state.record}
        sourceId={sourceId}
        back={back}
        embedded={embedded}
        onSaved={onSaved}
      />
    );
  return (
    <section aria-label={commandTitle} className="command-editor">
      {showParentLink && !hasContextNavigation && <ParentBackLink to={back} />}
      <h2>{commandTitle}</h2>
      <p>
        {addingContact
          ? "Choose email, phone number or mailing address, then enter the details. Add an optional label, such as Work or Mobile. The first contact of each type is automatically primary. These contact details are shared wherever this person or organization appears in the app."
          : editingContact
            ? "Update the contact details or make this the primary contact for its type. Saving a primary contact replaces the previous primary of that type. To switch away from a primary contact, make another contact of that type primary."
            : removingContact
              ? "Remove this contact from active use and retain its history. If it is primary and other contacts of the same type exist, make another primary first. Any role preferences that use this contact must be explicitly replaced or cleared below."
              : definition.formKey === "party.patch"
                ? "Update the name used throughout the app. Contact details and existing relationships stay unchanged."
                : definition.formKey === "portfolio.ownerships.replace"
                  ? "Review the complete owner list below, then save the ownership change. Saving an unfinished form keeps your input without changing ownership."
                  : definition.formKey === "portfolio.property.create"
                    ? "Start with the property name and address, choose its rental layout, and confirm the owners. Occupancy, leasing status and lease records can be added afterward."
                    : definition.formKey === "portfolio.space.classify"
                      ? "Add occupancy, leasing status, or both below. Save to apply your changes; saving an unfinished form does not update the property’s records."
                      : definition.formKey === "portfolio.availability.change"
                        ? "Choose whether the property is not open for leasing, open now, or open from a future date. For a future opening, enter the date. Add an optional note, then save."
                        : definition.formKey === "portfolio.occupancy.change"
                          ? "Choose the new occupancy status and when it takes effect in the property’s time zone. A future date schedules the change; it does not change today’s occupancy. Add an optional note, then save."
                          : ["portfolio.space.patch", "portfolio.property.patch"].includes(
                                definition.formKey,
                              )
                            ? "Edit the details below, then save your changes. Saving an unfinished form does not update the property’s records."
                            : definition.formKey === "portfolio.space.archive"
                              ? "Confirm that you want to archive this rental, then select Archive below. Saving an unfinished form does not archive it."
                              : definition.formKey === "maintenance.issue.create"
                                ? "Describe the issue, choose the property, and record who reported it. You can add appointments, quotes and evidence after saving."
                                : definition.formKey === "owner_concern.create"
                                  ? "Record what the owner has raised and which property it concerns. A concern does not change the property’s occupancy, rent or repair records."
                                  : (workflowIntroductions[definition.formKey] ??
                                    "Review the displayed record and make an explicit change. Saved input is an unfinished form, not an official record.")}
      </p>
      {(sourceCheckFailed || state.command === "rejected" || state.draft === "conflicted") &&
        currentSourceAction}
      <FormFeedback
        focusKey={feedbackAttempt}
        message={
          [
            error ?? state.error,
            ...Object.entries(state.problem?.fieldErrors ?? {}).map(
              ([name, errors]) => `${fieldName(name)}: ${errors.join(" ")}`,
            ),
          ]
            .filter(Boolean)
            .join("\n") || undefined
        }
      />
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
          if (
            ["portfolio.property.create", "portfolio.ownerships.replace"].includes(
              definition.formKey,
            ) &&
            ownershipShareProblem(values.ownerships)
          )
            return;
          void action(async () => {
            if (evidence && !attachment)
              throw new Error("Select the evidence file before submitting.");
            if (requiresRemovalConfirmation && !removalConfirmed)
              throw new Error("Confirm removal of this Lease participant.");
            if (definition.formKey === "finance.rent_receipt.create" && checkSource)
              await checkSource(values);
            validateForm(definition.schema, {
              ...record(clean(definition.schema, values)),
              idempotencyKey: crypto.randomUUID(),
            });
            if (checkSource && definition.formKey !== "finance.rent_receipt.create") {
              try {
                await checkSource({
                  ...values,
                  ...(definition.childKey && childId ? { [definition.childKey]: childId } : {}),
                });
                setSourceCheckFailed(false);
              } catch (cause) {
                setSourceCheckFailed(true);
                throw cause;
              }
            }
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
              {definition.formKey === "file.upload" && values.entityType === "maintenance_issue" ? (
                values.originalName && (
                  <dl className="money-facts">
                    <div>
                      <dt>Selected file</dt>
                      <dd>{scalar(values.originalName)}</dd>
                    </div>
                    <div>
                      <dt>Type</dt>
                      <dd>{scalar(values.mediaType)}</dd>
                    </div>
                    <div>
                      <dt>Size</dt>
                      <dd>{scalar(values.sizeBytes)} bytes</dd>
                    </div>
                  </dl>
                )
              ) : (
                <Facts
                  value={values}
                  fields={["originalName", "mediaType", "sizeBytes", "contentSha256"]}
                />
              )}
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
          {renderFields ? (
            renderFields(values, locked, (next) => form.setValue("data", next))
          ) : ["maintenance.appointment.create", "maintenance.appointment.update"].includes(
              definition.formKey,
            ) ? (
            <AppointmentFields
              schema={definition.schema}
              value={values}
              onChange={(next) => form.setValue("data", record(next))}
              disabled={locked}
            />
          ) : hasWorkCommandFields(definition.formKey) &&
            (definition.formKey !== "file.upload" || values.entityType === "maintenance_issue") ? (
            <WorkCommandFields
              formKey={definition.formKey}
              schema={definition.schema}
              value={values}
              onChange={(next) => form.setValue("data", record(next))}
              choices={choicesForValues?.(values) ?? choices}
              disabled={locked}
            />
          ) : definition.formKey === "task.create" ? (
            <TaskCreateFields
              schema={definition.schema}
              value={values}
              onChange={(next) => form.setValue("data", next)}
              choices={choicesForValues?.(values) ?? choices}
              disabled={locked}
            />
          ) : ["maintenance.issue.create", "owner_concern.create"].includes(definition.formKey) ? (
            <MaintenanceCreateFields
              schema={definition.schema}
              value={values}
              onChange={(next) => form.setValue("data", record(next))}
              choices={choicesForValues?.(values) ?? choices}
              disabled={locked}
              concern={definition.formKey === "owner_concern.create"}
            />
          ) : [
              "maintenance.issue.patch",
              "finance.expense_category.create",
              "finance.expense_category.patch",
            ].includes(definition.formKey) ? (
            <GroupedCommandFields
              schema={definition.schema}
              value={values}
              onChange={(next) => form.setValue("data", record(next))}
              choices={choicesForValues?.(values) ?? choices}
              disabled={locked}
              formKey={definition.formKey}
              originalReporter={initial.reporter}
            />
          ) : definition.formKey === "portfolio.property.create" ? (
            <PropertyCreateFields
              schema={definition.schema}
              value={values}
              onChange={(next) => form.setValue("data", next)}
              choices={choicesForValues?.(values) ?? choices}
              disabled={locked}
              onAddingChange={setAddingOwner}
            />
          ) : definition.formKey === "portfolio.ownerships.replace" ? (
            <OwnershipFields
              timeZone={propertyTimeZone}
              value={values}
              onChange={(next) => form.setValue("data", next)}
              choices={choices}
              disabled={locked}
              onAddingChange={setAddingOwner}
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
                addingContact || editingContact
                  ? {
                      ...definition.schema,
                      properties: Object.fromEntries(
                        ["methodKind", "value", "extension", "label", "isPrimary"]
                          .filter((key) => !!definition.schema.properties?.[key])
                          .map((key) => [key, definition.schema.properties![key]]),
                      ),
                    }
                  : evidence
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
              showChangeControls={!(addingContact || editingContact)}
            />
          )}
        </fieldset>
        {renderContext?.(values, locked, (next) => form.setValue("data", next))}
        {!locked && (
          <div className="command-form-actions" role="group" aria-label="Form actions">
            {saveActions}
            <DraftSaveStatus
              draft={state.draft}
              command={state.command}
              savedAt={state.record?.savedAt}
            />
          </div>
        )}
        {locked && (
          <DraftSaveStatus
            draft={state.draft}
            command={state.command}
            savedAt={state.record?.savedAt}
          />
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
      {state.draft === "conflicted" && (
        <p>
          Your input is retained. Return to the current record to review its latest revision before
          starting a new command.
        </p>
      )}
      {review && (
        <section aria-label="Current source review">
          <h3>Current source information</h3>
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
                setSourceCheckFailed(false);
              });
            }}
          >
            Keep my edits with this reviewed revision
          </button>
        </section>
      )}
      <RecoveryNavigation controller={controller} blocker={blocker} />
    </section>
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
