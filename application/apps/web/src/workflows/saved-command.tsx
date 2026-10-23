import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { record, scalar, type Workflow } from "@epm/contracts/workflows";
import { useWorkspace } from "../app/workspace-gate";
import { SourceWorkflowLink as Link } from "../shared/home-navigation";
import type { Recovery } from "../shared/recovery";
import { loadWorkflowResult } from "./workflow-result";
import { SavedItem } from "./saved-item";
import { SavedRentReceipt } from "./saved-rent-receipt";

export function useSaveCompletion() {
  const location = useLocation();
  const { scope } = useWorkspace();
  const key = `${scope.workspaceId}:${scope.runtimeEpoch}:${location.key}`;
  const [saved, setSaved] = useState<string>();
  const onSaved = useCallback(() => setSaved(key), [key]);
  return { completed: saved === key, onSaved };
}

function savesItem(key: string) {
  if (key.startsWith("portfolio.") && !/\.(property|space)\.(create|patch)$/.test(key))
    return key === "portfolio.ownerships.replace";
  if (key === "communication.draft.record") return false;
  return (
    /\.(create|add|record|admit|import|attach|upload|assign|designate|link|patch|edit|update|correct|follow_up)$/.test(
      key,
    ) || key === "lease.term.replace"
  );
}

function subject(key: string) {
  const names: [string, string][] = [
    ["portfolio.ownerships", "Ownership"],
    ["portfolio.property", "Property"],
    ["portfolio.space", "Home or unit"],
    ["party.contact", "Contact details"],
    ["party", "Name and identity"],
    ["tenant", "Tenant"],
    ["provider.category_assignment", "Category assignment"],
    ["provider.category", "Provider category"],
    ["provider.work_history", "Work history"],
    ["provider.reputation_link", "Reputation link"],
    ["provider.reference", "Reference"],
    ["provider.service", "Service"],
    ["provider.area", "Service area"],
    ["provider", "Provider"],
    ["maintenance.follow_up", "Follow-up task"],
    ["maintenance.issue", "Maintenance issue"],
    ["maintenance.appointment", "Appointment"],
    ["maintenance.cost", "Cost context"],
    ["maintenance.quote", "Provider quote"],
    ["maintenance.assignment", "Provider assignment"],
    ["maintenance.expense", "Expense association"],
    ["maintenance.journal", "Work entry"],
    ["maintenance.reporter", "Issue reporter"],
    ["owner_concern.follow_up", "Follow-up task"],
    ["owner_concern", "Owner concern"],
    ["communication", "Conversation"],
    ["intake", "Retained source"],
    ["task.reminder", "Reminder"],
    ["task", "Task"],
    ["inspection.template", "Inspection template"],
    ["inspection.evidence", "Inspection evidence"],
    ["inspection", "Inspection"],
    ["lease.participant", "Lease participant"],
    ["lease.termination.proposal", "Termination proposal"],
    ["lease.termination", "Termination request"],
    ["lease.renewal", "Renewal option"],
    ["lease.term", "Rent terms"],
    ["lease", "Lease draft"],
    ["owner_rent_report", "Owner rent report"],
    ["finance.expense_category", "Expense category"],
    ["finance.expense_refund", "Expense refund"],
    ["finance.expense", "Expense"],
    ["finance.rent_receipt", "Rent receipt"],
    ["finance.prepaid_check", "Prepaid check"],
    ["finance.deposit_account", "Deposit account"],
    ["finance.deposit_settlement", "Deposit settlement"],
    ["finance.deposit_deduction_source", "Deduction source"],
    ["finance.deposit_deduction", "Settlement deduction"],
    ["finance.deposit_credit", "Settlement credit"],
    ["finance.deposit_refund", "Deposit refund"],
    ["finance.deposit_receipt", "Deposit receipt"],
    ["file", "Evidence"],
  ];
  return names.find(([prefix]) => key === prefix || key.startsWith(prefix + "."))?.[1] ?? "Item";
}

function destination(
  form: string,
  value: unknown,
  target: string,
  source: string | undefined,
  back: string,
) {
  const item = record(value),
    profile = record(item.profile),
    party = record(item.party);
  const id = scalar(item.id ?? item.sourceId, target);
  const parent = scalar(item.partyId ?? party.id ?? profile.partyId, source ?? id);
  if (/^portfolio\.(occupancy|availability)\./.test(form) || form === "portfolio.space.classify")
    return { to: back, label: "Back to property" };
  if (form === "file.upload") return { to: `/money?file=${id}`, label: "Back to evidence" };
  if (form.startsWith("portfolio."))
    return {
      to: `/properties/${scalar(item.propertyId, id)}/${/space\./.test(form) ? "units" : ["portfolio.property.create", "portfolio.ownerships.replace"].includes(form) ? "overview" : "setup"}`,
      label: "Back to property",
    };
  if (form.startsWith("party."))
    return { to: `/parties?identity=${parent}`, label: "Back to contact details" };
  if (form.startsWith("tenant."))
    return { to: `/tenants?identity=${parent}`, label: "Back to tenant" };
  if (form.startsWith("provider.category."))
    return { to: "/settings/provider-categories", label: "Back to provider categories" };
  if (form.startsWith("provider."))
    return { to: `/providers/${parent}/details`, label: "Back to provider" };
  if (form.startsWith("intake."))
    return {
      to: `/conversations?intake=true&source=${scalar(item.sourceId, source ?? id)}`,
      label: "Back to retained source",
    };
  if (form.startsWith("lease."))
    return { to: `/leases/${scalar(item.leaseId, source ?? id)}/details`, label: "Back to lease" };
  if (form.startsWith("inspection.template."))
    return { to: "/leasing?templates=true", label: "Back to inspection templates" };
  if (form.startsWith("inspection."))
    return {
      to:
        form === "inspection.evidence.attach"
          ? back
          : `/inspections/${scalar(item.reportId, id || source)}`,
      label: "Back to inspection",
    };
  if (
    form.startsWith("task.") ||
    /follow_up$/.test(form) ||
    form === "maintenance.follow_up.create"
  )
    return {
      to: `/tasks?record=task&id=${scalar(record(item.task ?? item.followUpTask).id, /\.(create|follow_up)$/.test(form) ? id : (source ?? id))}`,
      label: "Back to task",
    };
  if (form.startsWith("maintenance."))
    return {
      to: `/maintenance?record=issue&id=${source ?? scalar(item.issueId, id)}`,
      label: "Back to maintenance issue",
    };
  if (form.startsWith("communication."))
    return {
      to: `/conversations?record=communication&id=${source ?? id}`,
      label: "Back to conversation",
    };
  if (form.startsWith("owner_concern."))
    return { to: `/maintenance?record=concern&id=${source ?? id}`, label: "Back to owner concern" };
  const kind = form.startsWith("owner_rent_report.")
    ? "report"
    : form.startsWith("finance.expense_category.")
      ? "category"
      : form.startsWith("finance.expense")
        ? "expense"
        : form.startsWith("finance.prepaid_check.")
          ? "check"
          : form.startsWith("finance.rent_receipt.")
            ? "receipt"
            : "deposit";
  return {
    to: `/money?record=${kind}&id=${scalar(item.expenseId ?? item.accountId, kind === "deposit" ? (source ?? id) : id)}`,
    label: `Back to ${kind === "report" ? "owner rent report" : kind === "category" ? "expense category" : kind === "check" ? "prepaid check" : kind === "receipt" ? "rent receipt" : kind === "deposit" ? "deposit account" : "expense"}`,
  };
}

export function SavedCommand({
  definition,
  recovery,
  sourceId,
  back,
  embedded,
  onSaved,
}: {
  definition: Workflow;
  recovery: Recovery;
  sourceId?: string;
  back: string;
  embedded: boolean;
  onSaved?: () => void;
}) {
  useEffect(() => onSaved?.(), [onSaved]);
  const { scope } = useWorkspace();
  const operation = recovery.receipt!.receiptId;
  const result = useQuery({
    queryKey: scope.key("saved-command", definition.formKey, operation),
    queryFn: ({ signal }) =>
      loadWorkflowResult(definition.formKey, operation, recovery.attemptKey!, signal),
    retry: false,
    staleTime: Infinity,
  });
  const name =
    definition.formKey === "party.patch"
      ? "Name"
      : definition.formKey === "party.create"
        ? "Contact"
        : subject(definition.formKey);
  const edited = /\.(patch|edit|update|correct|replace)$/.test(definition.formKey);
  const lifecycle = !savesItem(definition.formKey);
  const summary = record(recovery.receipt?.result);
  const target = scalar(summary.targetId ?? summary.resultId ?? summary.id);
  const rentReceipt = definition.formKey === "finance.rent_receipt.create";
  return (
    <SavedItem
      title={
        lifecycle ? `${definition.title} — complete` : `${name} ${edited ? "updated" : "saved"}`
      }
      value={rentReceipt ? undefined : result.data}
      embedded={embedded}
      destination={
        rentReceipt
          ? { to: `/money?tab=rent&leaseId=${sourceId}`, label: "Back to rent" }
          : destination(definition.formKey, result.data, target, sourceId, back)
      }
    >
      {rentReceipt && result.data !== undefined && (
        <SavedRentReceipt value={result.data} leaseId={sourceId!} />
      )}
      {result.isPending && <p role="status">Loading saved {name.toLowerCase()} details…</p>}
      {result.error && (
        <div role="alert">
          <p>
            {lifecycle ? "Your change is complete" : `Your ${name.toLowerCase()} was saved`}, but
            its details could not be loaded. No new save is needed.
          </p>
          <button type="button" onClick={() => void result.refetch()}>
            Retry saved {name.toLowerCase()} details
          </button>
        </div>
      )}
      {result.data !== undefined && definition.formKey === "finance.expense.create" && (
        <p>
          Evidence is optional.{" "}
          <Link
            to={`/money?workflow=file.upload&entityType=expense&entityId=${scalar(record(result.data).id)}&purpose=receipt`}
          >
            Add expense evidence
          </Link>
        </p>
      )}
    </SavedItem>
  );
}
