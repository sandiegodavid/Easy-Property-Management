import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api } from "@epm/contracts";
import type { components } from "@epm/contracts/generated";
import { workflows, record, scalar } from "@epm/contracts/workflows";
import { useWorkspace } from "../app/workspace-gate";
import { CommandLinks, CommandLoader } from "./command";
import { Facts, History, IdentityLookup, readResult } from "./reads";
import type { Choices } from "./fields";

export function ProviderWorkspace() {
  const route = useParams();
  const [params, setParams] = useSearchParams();
  const definition = workflows.find((item) => item.formKey === params.get("workflow"));
  const target = params.get("target") ?? route.id,
    child = params.get("child") ?? undefined;
  const { scope } = useWorkspace();
  const [session] = useState(() => crypto.randomUUID());
  const archived = params.get("history") === "true" || !!definition;
  const categories = useQuery({
    queryKey: definition
      ? scope.key("category-command-source", session)
      : scope.key("provider-categories", "all"),
    staleTime: definition ? Infinity : 0,
    refetchOnWindowFocus: !definition,
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/provider-categories", {
          signal,
          params: { query: { archiveState: "all" } },
        }),
      ),
  });
  const provider = useQuery<components["schemas"]["ProviderResponse"]>({
    queryKey: definition
      ? scope.key("provider-command-source", session, target)
      : scope.key("provider-record", target, archived),
    staleTime: definition ? Infinity : 0,
    refetchOnWindowFocus: !definition,
    placeholderData: (previous) => (previous?.party.id === target ? previous : undefined),
    enabled:
      !!target &&
      definition?.sourceKind !== "provider_category" &&
      definition?.formKey !== "provider.designate",
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/providers/{party_id}", {
          signal,
          params: { path: { party_id: target! }, query: { includeArchived: archived } },
        }),
      ),
  });
  const category = categories.data?.find((item) => item.id === target);
  const choices: Choices = {
    categoryId:
      categories.data
        ?.filter((item) => !item.archivedAt)
        .map((item) => ({ id: item.id, label: item.displayName, revision: item.revision })) ?? [],
    categoryIds:
      categories.data
        ?.filter((item) => !item.archivedAt)
        .map((item) => ({ id: item.id, label: item.displayName, revision: item.revision })) ?? [],
  };
  if (definition) {
    if (!definition.formKey.startsWith("provider."))
      return <p role="alert">Unsupported Provider workflow.</p>;
    if (definition.sourceKind && !target)
      return <p role="alert">Select the owning Provider or category first.</p>;
    if (
      categories.isPending ||
      (target &&
        definition.sourceKind === "provider" &&
        definition.formKey !== "provider.designate" &&
        provider.isPending)
    )
      return <p role="status">Loading displayed record…</p>;
    if (categories.error || provider.error)
      return <p role="alert">{categories.error?.message ?? provider.error?.message}</p>;
    if (definition.sourceKind === "provider_category" && !category)
      return <p role="alert">Category not found.</p>;
    const lists = provider.data
      ? [
          provider.data.services,
          provider.data.serviceAreas,
          provider.data.workHistory,
          provider.data.references,
          provider.data.reputationLinks,
          provider.data.categories,
        ]
      : [];
    const selected = lists
      .flat()
      .find((item) => item.id === child || record(item).assignmentId === child);
    if (child && !selected)
      return (
        <p role="alert">
          This child record is not visible in the selected Provider. Open history to select an
          archived record.
        </p>
      );
    const initial: Record<string, unknown> =
      definition.formKey === "provider.create"
        ? { party: { partyKind: "organization" }, selectionStatus: "neutral" }
        : definition.formKey === "provider.profile.patch"
          ? {
              selectionStatus: provider.data?.profile.selectionStatus,
              selectionReason: provider.data?.profile.selectionReason,
              notes: provider.data?.profile.notes,
            }
          : definition.formKey === "provider.category.create"
            ? { displayOrder: 0 }
            : definition.formKey === "provider.category.patch"
              ? {
                  displayName: category?.displayName,
                  description: category?.description,
                  displayOrder: category?.displayOrder,
                }
              : {};
    if (selected && definition.formKey.endsWith(".update"))
      for (const key of Object.keys(definition.schema.properties ?? {}))
        if (key in selected) initial[key] = record(selected)[key];
    if (definition.formKey === "provider.category_assignment.restore")
      initial.expectedCategoryRevision = categories.data?.find(
        (item) => item.id === selected?.id,
      )?.revision;
    return (
      <>
        <p>
          Profile, child and assignment changes use the Provider revision. Categories have their own
          revision. Category assignment does not create an engagement. Reputation links record
          external references, not verified endorsements.
        </p>
        <CommandLoader
          definition={definition}
          sourceId={target}
          childId={child}
          revision={
            definition.sourceKind === "provider_category"
              ? category!.revision
              : definition.formKey === "provider.designate"
                ? 0
                : (provider.data?.profile.revision ?? 0)
          }
          initial={initial}
          choices={choices}
        />
      </>
    );
  }
  if (target) {
    if (provider.isPending) return <p role="status">Loading Provider…</p>;
    if (provider.error) return <p role="alert">{provider.error.message}</p>;
    const item = provider.data;
    const active = !item.profile.archivedAt;
    return (
      <section>
        <h2>{item.party.displayName}</h2>
        <Link to="/providers">Provider directory</Link> ·{" "}
        <Link to={`/parties?identity=${target}`}>Shared identity and contacts</Link>
        <Facts
          value={item.profile}
          fields={[
            "revision",
            "selectionStatus",
            "selectionReason",
            "notes",
            "archivedAt",
            "updatedAt",
          ]}
        />
        <CommandLinks
          target={target}
          keys={
            active
              ? [
                  "provider.profile.patch",
                  "provider.archive",
                  "provider.category_assignment.assign",
                ]
              : ["provider.restore"]
          }
          title="Provider actions"
        />
        <label>
          <input
            type="checkbox"
            checked={archived}
            onChange={(event) => {
              const next = new URLSearchParams(params);
              next.set("history", String(event.target.checked));
              setParams(next, { flushSync: true });
            }}
          />
          Include archived contextual history
        </label>
        <section className="context-section">
          <h3>Categories and assignment history</h3>
          <p>
            Only active assignments, active categories and an active Provider are effective.
            Category selection does not imply an engagement.
          </p>
          {item.categories.map((category) => (
            <article key={category.assignmentId}>
              <Facts
                value={category}
                fields={[
                  "displayName",
                  "description",
                  "assignmentArchivedAt",
                  "assignmentArchiveReason",
                  "archivedAt",
                  "archiveReason",
                ]}
              />
              {active && (
                <CommandLinks
                  target={target}
                  child={category.assignmentId}
                  keys={
                    category.assignmentArchivedAt
                      ? ["provider.category_assignment.restore"]
                      : ["provider.category_assignment.archive"]
                  }
                  title={`Assignment ${category.displayName}`}
                />
              )}
            </article>
          ))}
        </section>
        <ProviderChildren
          kind="service"
          title="Services"
          rows={item.services}
          fields={["displayName"]}
          target={target}
          active={active}
        />
        <ProviderChildren
          kind="area"
          title="Service areas"
          rows={item.serviceAreas}
          fields={["displayName", "countryCode"]}
          target={target}
          active={active}
        />
        <ProviderChildren
          kind="work_history"
          title="Work history"
          rows={item.workHistory}
          fields={["performedOn", "summary", "propertyId", "outcomeNotes"]}
          target={target}
          active={active}
        />
        <ProviderChildren
          kind="reference"
          title="References"
          rows={item.references}
          fields={["referenceName", "organizationName", "relationship", "email", "phone", "notes"]}
          target={target}
          active={active}
        />
        <ProviderChildren
          kind="reputation_link"
          title="Reputation links"
          rows={item.reputationLinks}
          fields={["sourceKind", "sourceName", "url", "lastCheckedOn", "notes"]}
          target={target}
          active={active}
        />
        <History kind="provider_profile" id={target} />
      </section>
    );
  }
  return (
    <>
      <h2>Providers</h2>
      <p>
        Shared identities across services, with recorded references, reputation and work history.
      </p>
      <Link to="/parties">Shared identities and tenants</Link>
      <CommandLinks
        keys={["provider.create", "provider.category.create"]}
        title="Create Provider or category"
      />
      <details>
        <summary>Use an existing identity</summary>
        <IdentityLookup
          onSelect={(id) => setParams({ workflow: "provider.designate", target: id })}
        />
      </details>
      <ProviderDirectory />
      <details>
        <summary>Category administration</summary>
        {categories.isPending && <p role="status">Loading categories…</p>}
        {categories.error && <p role="alert">{categories.error.message}</p>}
        {categories.data?.map((category) => (
          <article key={category.id}>
            <h3>{category.displayName}</h3>
            <Facts
              value={category}
              fields={[
                "revision",
                "description",
                "displayOrder",
                "effectiveProviderCount",
                "archivedAt",
                "archiveReason",
              ]}
            />
            <CommandLinks
              target={category.id}
              keys={
                category.archivedAt
                  ? ["provider.category.restore"]
                  : ["provider.category.patch", "provider.category.archive"]
              }
              title={`Category ${category.displayName}`}
            />
            <History kind="provider_category" id={category.id} />
          </article>
        ))}
      </details>
    </>
  );
}

function ProviderChildren({
  kind,
  title,
  rows,
  fields,
  target,
  active,
}: {
  kind: string;
  title: string;
  rows: { id: string; archivedAt: string | null }[];
  fields: string[];
  target: string;
  active: boolean;
}) {
  return (
    <section className="context-section">
      <h3>{title}</h3>
      {active && (
        <CommandLinks
          target={target}
          keys={[`provider.${kind}.add`]}
          title={`Add ${title.toLowerCase()}`}
        />
      )}
      {rows.map((row) => (
        <article key={row.id}>
          <Facts value={row} fields={[...fields, "archivedAt"]} />
          {active && (
            <CommandLinks
              target={target}
              child={row.id}
              keys={
                row.archivedAt
                  ? [`provider.${kind}.restore`]
                  : [`provider.${kind}.update`, `provider.${kind}.archive`]
              }
              title={`Actions for ${scalar(record(row).displayName ?? record(row).summary ?? record(row).referenceName ?? record(row).sourceKind, title)}`}
            />
          )}
        </article>
      ))}
    </section>
  );
}

function ProviderDirectory() {
  const { scope } = useWorkspace();
  const [params, setParams] = useSearchParams();
  const archive = params.get("archiveState"),
    selection = params.get("selectionStatus"),
    categoryState = params.get("categoryState");
  const result = useQuery({
    queryKey: scope.key("provider-directory", params.toString()),
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/providers", {
          signal,
          params: {
            query: {
              limit: 50,
              cursor: params.get("cursor") ?? undefined,
              search: params.get("q") ?? undefined,
              archiveState: archive === "archived" || archive === "all" ? archive : "active",
              selectionStatus:
                selection === "preferred" || selection === "avoid" || selection === "neutral"
                  ? selection
                  : undefined,
              categoryState:
                categoryState === "categorized" || categoryState === "uncategorized"
                  ? categoryState
                  : undefined,
              service: params.get("service") ?? undefined,
              serviceArea: params.get("serviceArea") ?? undefined,
              hasReference: params.get("hasReference") === "true" ? true : undefined,
              propertyId: params.get("propertyId") ?? undefined,
              categoryId: params.get("categoryId") ?? undefined,
            },
          },
        }),
      ),
  });
  return (
    <section aria-label="Provider directory">
      <form
        className="directory-filters"
        onSubmit={(event) => {
          event.preventDefault();
          const data = new FormData(event.currentTarget);
          const next = new URLSearchParams();
          for (const [key, value] of data)
            if (typeof value === "string" && value) next.set(key, value);
          setParams(next);
        }}
      >
        <label>
          Search Providers
          <input name="q" defaultValue={params.get("q") ?? ""} maxLength={240} />
        </label>
        <label>
          Archive state
          <select name="archiveState" defaultValue={archive ?? "active"}>
            <option value="active">Active</option>
            <option value="archived">Archived</option>
            <option value="all">All</option>
          </select>
        </label>
        <label>
          Selection status
          <select name="selectionStatus" defaultValue={selection ?? ""}>
            <option value="">Any</option>
            <option value="preferred">Preferred</option>
            <option value="neutral">Neutral</option>
            <option value="avoid">Avoid</option>
          </select>
        </label>
        <label>
          Category state
          <select name="categoryState" defaultValue={categoryState ?? ""}>
            <option value="">Any</option>
            <option value="categorized">Categorized</option>
            <option value="uncategorized">Uncategorized</option>
          </select>
        </label>
        <label>
          Service
          <input name="service" defaultValue={params.get("service") ?? ""} maxLength={160} />
        </label>
        <label>
          Service area
          <input
            name="serviceArea"
            defaultValue={params.get("serviceArea") ?? ""}
            maxLength={160}
          />
        </label>
        <label>
          <input
            type="checkbox"
            name="hasReference"
            value="true"
            defaultChecked={params.get("hasReference") === "true"}
          />
          Has reference
        </label>
        <button>Apply Provider filters</button>
      </form>
      {result.isPending && <p role="status">Loading Providers…</p>}
      {result.error && (
        <p role="alert">
          {result.error.message}
          <button
            onClick={() => {
              const next = new URLSearchParams(params);
              next.delete("cursor");
              setParams(next);
              void result.refetch();
            }}
          >
            Refresh Providers
          </button>
        </p>
      )}
      {result.data && (
        <>
          <p>Showing {result.data.items.length} Providers on this bounded page.</p>
          {result.data.items.length === 0 && <p>No matching Providers on this page.</p>}
          {result.data.items.map((item) => (
            <article className="context-section" key={item.party.id}>
              <h3>
                <Link
                  state={{ returnTo: `/providers?${params}` }}
                  to={`/providers/${item.party.id}/details`}
                >
                  {item.party.displayName}
                </Link>
              </h3>
              <Facts
                value={item.profile}
                fields={["selectionStatus", "selectionReason", "archivedAt"]}
              />
              <p>
                {item.categories.map((category) => category.displayName).join(", ") ||
                  "Uncategorized"}
              </p>
              <p>{item.services.map((service) => service.displayName).join(", ")}</p>
              <p>{item.serviceAreas.map((area) => area.displayName).join(", ")}</p>
              <p>
                {item.workHistoryCount} work records · {item.referenceCount} references ·{" "}
                {item.reputationLinkCount} reputation links
              </p>
            </article>
          ))}
          {result.data.nextCursor && (
            <button
              onClick={() => {
                const next = new URLSearchParams(params);
                next.set("cursor", result.data?.nextCursor ?? "");
                setParams(next);
              }}
            >
              Next Providers
            </button>
          )}
        </>
      )}
    </section>
  );
}
