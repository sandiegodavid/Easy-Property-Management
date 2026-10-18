import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ParentBackLink } from "../shared/home-navigation";
import { api } from "@epm/contracts";
import { workflows } from "@epm/contracts/workflows";
import { useWorkspace } from "../app/workspace-gate";
import { CommandLoader } from "./command";
import { useSaveCompletion } from "./saved-command";
import { readResult } from "./reads";
import { ContactList, IdentityDetail } from "./identity-detail";
import { TenantDirectory } from "./tenant-directory";

export function IdentityWorkspace() {
  const { completed, onSaved } = useSaveCompletion();
  const [params] = useSearchParams();
  const id = params.get("identity"),
    definition = workflows.find((item) => item.formKey === params.get("workflow"));
  const target = params.get("target") ?? id ?? undefined,
    child = params.get("child") ?? undefined;
  const { scope } = useWorkspace();
  const [session] = useState(() => crypto.randomUUID());
  const sourceId = definition?.sourceKind ? target : id;
  const party = useQuery({
    queryKey: definition
      ? scope.key("identity-command-source", session, sourceId)
      : scope.key("identity-record", sourceId),
    staleTime: definition ? Infinity : 0,
    refetchOnWindowFocus: !definition,
    enabled: !!sourceId,
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/parties/{party_id}", {
          signal,
          params: { path: { party_id: sourceId! } },
        }),
      ),
  });
  const contacts = useQuery({
    queryKey: scope.key("identity-record", sourceId),
    enabled: !!sourceId && definition?.formKey === "party.contact.add",
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/parties/{party_id}", {
          signal,
          params: { path: { party_id: sourceId! } },
        }),
      ),
  });
  const tenant = useQuery({
    queryKey: definition
      ? scope.key("tenant-command-source", session, sourceId)
      : scope.key("tenant-record", sourceId),
    staleTime: definition ? Infinity : 0,
    refetchOnWindowFocus: !definition,
    enabled:
      !!sourceId &&
      ((!!party.data && !definition) ||
        (!!definition?.formKey.startsWith("tenant.") && definition.formKey !== "tenant.designate")),
    queryFn: async ({ signal }) => {
      const response = await api.GET("/api/tenants/{party_id}", {
        signal,
        params: { path: { party_id: sourceId! } },
      });
      if (response.response.status === 404) return null;
      return readResult(response);
    },
  });
  if (definition && !/^(party|tenant)\./.test(definition.formKey))
    return <p role="alert">Unsupported identity workflow.</p>;
  if (sourceId && party.isPending) return <p role="status">Loading identity…</p>;
  if (party.error) return <p role="alert">{party.error.message}</p>;
  if (definition) {
    if (definition.sourceKind && !target) return <p role="alert">Select an identity first.</p>;
    if (definition.sourceKind === "tenant" && definition.formKey !== "tenant.designate") {
      if (tenant.isPending) return <p role="status">Loading Tenant revision…</p>;
      if (tenant.error) return <p role="alert">{tenant.error.message}</p>;
    }
    const contact = party.data?.contactMethods?.find((item) => item.id === child);
    if (child && !contact)
      return <p role="alert">This contact does not belong to the selected identity.</p>;
    const revision =
      definition.formKey === "tenant.designate"
        ? 0
        : definition.sourceKind === "tenant"
          ? (tenant.data?.profile.revision ?? 0)
          : (party.data?.revision ?? 0);
    const initial: Record<string, unknown> = definition.formKey.endsWith(".create")
      ? { partyKind: "individual" }
      : definition.formKey === "party.patch"
        ? { displayName: party.data?.displayName }
        : definition.formKey === "party.contact.add"
          ? { methodKind: "email" }
          : definition.formKey === "party.contact.update"
            ? {
                methodKind: contact?.methodKind,
                value: contact?.displayValue,
                extension: contact?.extension ?? "",
                label: contact?.label ?? "",
                isPrimary: params.get("setPrimary") === "true" || contact?.isPrimary,
              }
            : definition.formKey === "tenant.profile.patch"
              ? {
                  notes: tenant.data?.profile.notes,
                  doNotContact: tenant.data?.profile.doNotContact,
                  preferredContactMethodId: tenant.data?.profile.preferredContactMethodId,
                  officialIds: tenant.data?.profile.officialIds ?? [],
                }
              : {};
    if (definition.formKey === "party.contact.archive") initial.referenceResolutions = [];
    const editingName = definition.formKey === "party.patch";
    const addingContact = definition.formKey === "party.contact.add";
    const editingContact = definition.formKey === "party.contact.update";
    const removingContact = definition.formKey === "party.contact.archive";
    const personEdit = editingName || addingContact || editingContact || removingContact;
    return (
      <div className={personEdit ? "person-edit-command" : undefined}>
        {!completed &&
          (personEdit && party.data ? (
            <>
              <ParentBackLink to={`/parties?identity=${party.data.id}`}>
                ← Back to {party.data.displayName}
              </ParentBackLink>
              <p className="person-edit-context">
                {addingContact
                  ? "Adding contact details for "
                  : editingContact
                    ? "Editing contact details for "
                    : removingContact
                      ? "Removing contact details for "
                      : "Changing the name for "}
                <strong>{party.data.displayName}</strong>
              </p>
              {(editingContact || removingContact) && contact && <p>{contact.displayValue}</p>}
            </>
          ) : (
            <p>
              Identity and contact changes use the Party revision. Tenant preferences and lifecycle
              use the separate Tenant revision. Archiving a preferred contact requires an explicit
              replacement or clear decision for each owning role.
            </p>
          ))}
        {!completed && definition.formKey === "tenant.profile.patch" && (
          <p>
            Official IDs are required before lease execution, not to save a tenant profile. Enter
            only the last four letters or digits. Do not enter full document numbers or upload
            scans.
          </p>
        )}
        <CommandLoader
          onSaved={onSaved}
          definition={definition}
          sourceId={target}
          childId={child}
          revision={revision}
          initial={initial}
          choices={{
            preferredContactMethodId:
              party.data?.contactMethods
                ?.filter((item) => item.status === "active")
                .map((item) => ({
                  id: item.id,
                  label: `${item.methodKind}: ${item.displayValue}`,
                })) ?? [],
            replacementContactMethodId:
              party.data?.contactMethods
                ?.filter((item) => item.status === "active" && item.id !== child)
                .map((item) => ({ id: item.id, label: item.displayValue })) ?? [],
          }}
        />
        {!completed && addingContact && party.data && (
          <>
            {contacts.error && <p role="alert">{contacts.error.message}</p>}
            <ContactList party={contacts.data ?? party.data} />
          </>
        )}
      </div>
    );
  }
  if (id && party.data)
    return (
      <IdentityDetail
        party={party.data}
        tenant={tenant.data}
        tenantLoading={tenant.isFetching}
        tenantError={tenant.error?.message}
      />
    );
  return <TenantDirectory />;
}
