import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "@epm/contracts";
import { workflows, scalar } from "@epm/contracts/workflows";
import { useWorkspace } from "../app/workspace-gate";
import { CommandLinks, CommandLoader } from "./command";
import { Facts, History, IdentityLookup, readResult } from "./reads";

export function IdentityWorkspace() {
  const [params, setParams] = useSearchParams();
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
  const search = params.get("q") ?? "",
    cursor = params.get("cursor") ?? undefined;
  const results = useQuery({
    queryKey: scope.key("tenant-find", search, cursor, params.get("archived")),
    enabled: !id && !definition && search.trim().length >= 2,
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/operator/search", {
          signal,
          params: {
            query: {
              q: search,
              group: "tenants",
              limit: 20,
              cursor,
              includeArchived: params.get("archived") === "true",
            },
          },
        }),
      ),
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
        : definition.formKey === "party.contact.update"
          ? {
              methodKind: contact?.methodKind,
              value: contact?.displayValue,
              extension: contact?.extension,
              label: contact?.label,
            }
          : definition.formKey === "tenant.profile.patch"
            ? {
                notes: tenant.data?.profile.notes,
                doNotContact: tenant.data?.profile.doNotContact,
                preferredContactMethodId: tenant.data?.profile.preferredContactMethodId,
              }
            : {};
    if (definition.formKey === "party.contact.archive") initial.referenceResolutions = [];
    return (
      <>
        <p>
          Identity and contact changes use the Party revision. Tenant preferences and lifecycle use
          the separate Tenant revision. Archiving a preferred contact requires an explicit
          replacement or clear decision for each owning role.
        </p>
        <CommandLoader
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
      </>
    );
  }
  return (
    <section>
      <h2>Shared identities and tenants</h2>
      <p>
        One identity can hold multiple roles. Editing its name or contacts updates the shared
        identity; archiving a role preserves identity and history.
      </p>
      <Link to="/properties">Properties</Link> · <Link to="/providers">Providers</Link>
      <CommandLinks keys={["party.create", "tenant.create"]} title="Create identity or tenant" />
      {!id && (
        <>
          <IdentityLookup onSelect={(identity) => setParams({ identity })} />
          <form
            onSubmit={(event) => {
              event.preventDefault();
              const data = new FormData(event.currentTarget);
              setParams({
                q: scalar(data.get("q")),
                archived: String(data.get("archived") === "on"),
              });
            }}
          >
            <label>
              Find tenant
              <input name="q" minLength={2} maxLength={240} required defaultValue={search} />
            </label>
            <label>
              <input
                name="archived"
                type="checkbox"
                defaultChecked={params.get("archived") === "true"}
              />
              Include archived tenants
            </label>
            <button>Find tenants</button>
          </form>
          {results.isFetching && <p role="status">Finding tenants…</p>}
          {results.error && (
            <p role="alert">
              {results.error.message}
              <button
                onClick={() => {
                  const next = new URLSearchParams(params);
                  next.delete("cursor");
                  setParams(next);
                }}
              >
                Restart tenant search
              </button>
            </p>
          )}
          {results.data?.groups.tenants?.availability === "unavailable" && (
            <p>Tenant search is unavailable.</p>
          )}
          {results.data?.groups.tenants?.availability === "available" && (
            <>
              <p>
                {results.data.groups.tenants.matchingTotal} matching tenants · As of{" "}
                {results.data.asOf}
              </p>
              {results.data.groups.tenants.items?.map((item) => (
                <p key={item.sourceId}>
                  <Link to={`/parties?identity=${item.sourceId}`}>{item.label}</Link> ·{" "}
                  {item.context} {item.archived && "Archived"}
                </p>
              ))}
              {results.data.groups.tenants.nextCursor && (
                <button
                  onClick={() => {
                    const next = new URLSearchParams(params);
                    next.set("cursor", results.data?.groups.tenants?.nextCursor ?? "");
                    setParams(next);
                  }}
                >
                  Next tenants
                </button>
              )}
            </>
          )}
        </>
      )}
      {party.data && (
        <section className="context-section">
          <h3>{party.data.displayName}</h3>
          <Facts
            value={party.data}
            fields={["partyKind", "revision", "createdAt", "updatedAt", "archivedAt"]}
          />
          <p>Active roles: {party.data.activeRoles?.join(", ") || "none"}</p>
          <CommandLinks
            target={party.data.id}
            keys={
              party.data.archivedAt
                ? ["party.restore"]
                : [
                    "party.patch",
                    "party.contact.add",
                    "party.archive",
                    ...(tenant.data === null ? ["tenant.designate"] : []),
                    ...(!party.data.activeRoles?.includes("provider")
                      ? ["provider.designate"]
                      : []),
                  ]
            }
            title="Identity actions"
          />
          <h4>Contacts and history</h4>
          {party.data.contactMethods?.map((method) => (
            <article key={method.id}>
              <Facts
                value={method}
                fields={["methodKind", "displayValue", "extension", "label", "status"]}
              />
              <CommandLinks
                target={party.data.id}
                child={method.id}
                keys={
                  method.status === "active"
                    ? ["party.contact.update", "party.contact.archive"]
                    : ["party.contact.restore"]
                }
                title={`Actions for ${method.displayValue}`}
              />
            </article>
          ))}
          <History kind="party" id={party.data.id} />
        </section>
      )}
      {tenant.isFetching && <p role="status">Loading Tenant…</p>}
      {tenant.error && <p role="alert">{tenant.error.message}</p>}
      {tenant.data && (
        <section className="context-section">
          <h3>Tenant preferences</h3>
          <Facts
            value={tenant.data.profile}
            fields={["revision", "preferredContactMethodId", "doNotContact", "notes", "archivedAt"]}
          />
          <CommandLinks
            target={tenant.data.id}
            keys={
              tenant.data.profile.archivedAt
                ? ["tenant.restore"]
                : ["tenant.profile.patch", "tenant.archive"]
            }
            title="Tenant actions"
          />
          <History kind="tenant_profile" id={tenant.data.id} />
        </section>
      )}
    </section>
  );
}
