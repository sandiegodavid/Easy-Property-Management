import { DynamicFilterForm } from "../shared/dynamic-filter-form";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { ParentBackLink, SourceWorkflowLink as Link } from "../shared/home-navigation";
import { api } from "@epm/contracts";
import type { components } from "@epm/contracts/generated";
import { workflows, record, scalar } from "@epm/contracts/workflows";
import { useWorkspace } from "../app/workspace-gate";
import { CommandLinks, CommandLoader } from "./command";
import { Facts, History, readResult } from "./reads";
import { WorkJournal } from "./work-journal";
import type { Choices } from "./fields";
import { OfficialIdList } from "../shared/official-identification";
import { formatHomeTime } from "../shared/home-time";
import { ReadableFacts } from "./readable-facts";

type Category = components["schemas"]["app__modules__vendors__api__router__CategoryResponse"];

export function ProviderWorkspace({ catalogOnly = false }: { catalogOnly?: boolean }) {
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
              officialIds: provider.data?.profile.officialIds,
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
          returnTo={
            definition.formKey.startsWith("provider.category.")
              ? "/settings/provider-categories"
              : target
                ? `/providers/${target}/details`
                : "/providers"
          }
          choices={choices}
        />
      </>
    );
  }
  if (target) {
    if (provider.isPending || provider.error)
      return (
        <>
          <ParentBackLink to="/providers">← Back to Providers</ParentBackLink>
          {provider.error ? (
            <p role="alert">{provider.error.message}</p>
          ) : (
            <p role="status">Loading Provider…</p>
          )}
        </>
      );
    const item = provider.data;
    const active = !item.profile.archivedAt;
    return (
      <section aria-label="Provider record" className="provider-detail">
        <ParentBackLink to="/providers">← Back to Providers</ParentBackLink>
        <header className="record-detail-heading">
          <div>
            <h2>{item.party.displayName}</h2>
            <p className="record-detail-note">
              {active ? "Active provider" : "Archived provider"} ·{" "}
              {item.party.partyKind === "organization" ? "Business" : "Individual"}
            </p>
          </div>
          <CommandLinks
            target={target}
            keys={active ? ["provider.profile.patch"] : ["provider.restore"]}
            labels={{ "provider.profile.patch": "Edit provider" }}
            title="Provider actions"
            asButtons
            collapsible={false}
          />
        </header>
        <section className="record-detail-panel" aria-label="Provider summary">
          <Facts
            value={item.profile}
            fields={[
              "selectionStatus",
              ...(item.profile.selectionReason ? ["selectionReason"] : []),
              ...(item.profile.notes ? ["notes"] : []),
            ]}
          />
          <Link className="button-link" to={`/parties?identity=${target}`}>
            View contact details
          </Link>
        </section>
        <section className="context-section" aria-label="Official identification">
          <header className="person-detail-section-heading">
            <h3>Official identification</h3>
            {active && (
              <CommandLinks
                target={target}
                keys={["provider.profile.patch"]}
                labels={{ "provider.profile.patch": "Manage official IDs" }}
                title="Manage official IDs"
                asButtons
                collapsible={false}
              />
            )}
          </header>
          <p>
            Record at least one official ID before assigning maintenance work. Full ID numbers are
            optional and hidden until you choose to show them. Recording an ID does not verify
            identity, qualifications or license validity.
          </p>
          {item.profile.officialIds.length ? (
            <OfficialIdList items={item.profile.officialIds} />
          ) : (
            <p>
              No official ID recorded. You can save this profile, but cannot assign maintenance work
              yet.
            </p>
          )}
        </section>
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
          Show archived records
        </label>
        <section className="context-section">
          <header className="person-detail-section-heading">
            <h3>Categories</h3>
            {active && (
              <CommandLinks
                target={target}
                keys={["provider.category_assignment.assign"]}
                title="Category actions"
                labels={{ "provider.category_assignment.assign": "Add category" }}
                asButtons
                collapsible={false}
              />
            )}
          </header>
          <p>Categories describe this provider’s services, not an engagement or endorsement.</p>
          {!item.categories.length && <p className="record-detail-note">None recorded.</p>}
          {item.categories.map((category) => (
            <article className="child-record-card" key={category.assignmentId}>
              <header className="child-record-heading">
                <h4>{category.displayName}</h4>
                <span className="record-pill">
                  {category.assignmentArchivedAt
                    ? "Assignment archived"
                    : category.archivedAt
                      ? "Category archived"
                      : "Active"}
                </span>
              </header>
              <ReadableFacts
                value={category}
                fields={[
                  "description",
                  ...(category.assignmentArchivedAt
                    ? ["assignmentArchivedAt", "assignmentArchiveReason"]
                    : []),
                  ...(category.archivedAt ? ["archivedAt", "archiveReason"] : []),
                ].filter((key) => record(category)[key] != null)}
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
        <div className="provider-detail-sections">
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
            fields={[
              "referenceName",
              "organizationName",
              "relationship",
              "email",
              "phone",
              "notes",
            ]}
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
        </div>
        <WorkJournal id={target} provider />
        <details className="record-detail-section">
          <summary>Record details and history</summary>
          <Facts
            value={{
              updatedAt: formatHomeTime(item.profile.updatedAt),
              archivedAt: item.profile.archivedAt ? formatHomeTime(item.profile.archivedAt) : null,
            }}
            fields={["updatedAt", "archivedAt"]}
            verbatim
          />
          <History kind="provider_profile" id={target} />
          {active && (
            <CommandLinks target={target} keys={["provider.archive"]} title="Archive provider" />
          )}
        </details>
      </section>
    );
  }
  if (!catalogOnly)
    return (
      <section className="provider-directory-page" aria-label="Providers">
        <header className="provider-directory-heading">
          <h2>Providers</h2>
          <CommandLinks
            keys={["provider.create"]}
            title="Provider actions"
            asButtons
            collapsible={false}
          />
        </header>
        {categories.error && (
          <p role="alert">
            Provider categories are unavailable.{" "}
            <button type="button" onClick={() => void categories.refetch()}>
              Retry categories
            </button>
          </p>
        )}
        <ProviderDirectory categories={categories.data ?? []} />
        <footer className="provider-directory-footer">
          <Link to="/settings/provider-categories">Manage provider categories</Link>
        </footer>
      </section>
    );
  return (
    <div className="provider-category-page">
      <header className="provider-category-heading">
        <div>
          <h2>Provider categories</h2>
          <p className="ui-muted">Organize providers by the kind of work they do.</p>
        </div>
        <CommandLinks
          keys={["provider.category.create"]}
          title="Add category"
          labels={{ "provider.category.create": "Add category" }}
          collapsible={false}
          asButtons
        />
      </header>
      <p className="provider-category-guidance">
        Categories group providers, such as Plumbing or Legal / Attorney. Services describe specific
        offerings or practice areas within a provider’s profile.
      </p>
      {categories.isPending && <p role="status">Loading categories…</p>}
      {categories.error && (
        <p role="alert">
          Categories are unavailable.{" "}
          <button type="button" onClick={() => void categories.refetch()}>
            Retry categories
          </button>
        </p>
      )}
      {(["active", "archived"] as const).map((state) => {
        const items = categories.data?.filter((category) =>
          state === "active" ? !category.archivedAt : !!category.archivedAt,
        );
        return (
          <section
            key={state}
            className="provider-category-section"
            aria-label={`${state === "active" ? "Active" : "Archived"} Provider categories`}
          >
            <header className="provider-category-section-heading">
              <h3>{state === "active" ? "Active categories" : "Archived categories"}</h3>
              {items && (
                <span className="provider-category-count">
                  {items.length} {items.length === 1 ? "category" : "categories"}
                </span>
              )}
            </header>
            {state === "archived" && (
              <p className="ui-muted">
                Archived categories are kept for history and can be restored. They are not used to
                group active providers.
              </p>
            )}
            {items?.length === 0 && (
              <p className="provider-category-empty">
                {state === "active"
                  ? "No active categories. Add a category to start organizing providers."
                  : "No archived categories."}
              </p>
            )}
            {!!items?.length && (
              <ul className="provider-category-grid">
                {items.map((category) => (
                  <li key={category.id}>
                    <ProviderCategoryCard category={category} canWrite={scope.canWrite} />
                  </li>
                ))}
              </ul>
            )}
          </section>
        );
      })}
    </div>
  );
}

function ProviderCategoryCard({ category, canWrite }: { category: Category; canWrite: boolean }) {
  const archived = !!category.archivedAt;
  return (
    <article className="provider-category-card" aria-labelledby={`category-${category.id}`}>
      <header>
        <h4 id={`category-${category.id}`}>{category.displayName}</h4>
        <span className="provider-category-state">{archived ? "Archived" : "Active"}</span>
      </header>
      {category.description && (
        <p className="provider-category-description">{category.description}</p>
      )}
      {!archived && (
        <p className="provider-category-providers">
          {category.effectiveProviderCount > 0 ? (
            <Link to={`/providers?categoryId=${category.id}`}>
              {category.effectiveProviderCount}{" "}
              {category.effectiveProviderCount === 1 ? "provider" : "providers"}
              <span className="ui-sr-only"> in {category.displayName}</span>
            </Link>
          ) : (
            "No active providers"
          )}
        </p>
      )}
      {category.archivedAt && (
        <div className="provider-category-archive">
          <p>
            Archived{" "}
            <time dateTime={category.archivedAt}>{formatHomeTime(category.archivedAt)}</time>
          </p>
          {category.archiveReason && <p>{category.archiveReason}</p>}
        </div>
      )}
      {canWrite && (
        <nav className="provider-category-actions" aria-label={`${category.displayName} actions`}>
          {(archived ? ["restore"] : ["patch", "archive"]).map((action) => (
            <Link
              key={action}
              className={
                action === "archive"
                  ? "provider-category-action provider-category-action-subtle"
                  : "provider-category-action"
              }
              to={`/providers?workflow=provider.category.${action}&target=${category.id}`}
              state={{ returnTo: "/settings/provider-categories" }}
            >
              {action === "patch"
                ? "Edit category"
                : action === "archive"
                  ? "Archive category"
                  : "Restore category"}
              <span className="ui-sr-only"> {category.displayName}</span>
            </Link>
          ))}
        </nav>
      )}
      <footer className="provider-category-footer">
        <span className="ui-muted">Display order: {category.displayOrder}</span>
        <History kind="provider_category" id={category.id} presentation="timeline" />
      </footer>
    </article>
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
    <section className="context-section" aria-label={title}>
      <header className="person-detail-section-heading">
        <h3>{title}</h3>
        {active && (
          <CommandLinks
            target={target}
            keys={[`provider.${kind}.add`]}
            title={`Add ${title.toLowerCase()}`}
            asButtons
            collapsible={false}
          />
        )}
      </header>
      {kind === "work_history" && (
        <p>Manually recorded prior work. Maintenance owns issue-backed work journals.</p>
      )}
      {kind === "reputation_link" && (
        <p>
          These are manually recorded pointers, not verified ratings or endorsements. Last checked
          records your review date. Opening a link visits an external site; saving and reading this
          record do not contact it.
        </p>
      )}
      {rows.length === 0 && <p className="record-detail-note">None recorded.</p>}
      {rows.map((row) => (
        <article className="child-record-card" key={row.id}>
          <header className="child-record-heading">
            <h4>
              {scalar(
                record(row).displayName ??
                  record(row).summary ??
                  record(row).referenceName ??
                  record(row).sourceName,
                title.replace(/s$/, ""),
              )}
            </h4>
            <span className="record-pill">{row.archivedAt ? "Archived" : "Active"}</span>
          </header>
          <ReadableFacts
            value={row}
            fields={[...fields, "archivedAt"].filter(
              (key) =>
                !key.endsWith("Id") &&
                !["displayName", "summary", "referenceName", "sourceName"].includes(key) &&
                record(row)[key] != null &&
                record(row)[key] !== "",
            )}
          />
          {kind === "reputation_link" && (
            <>
              {!row.archivedAt && reputationUrl(row) && (
                <a
                  href={reputationUrl(row)}
                  target="_blank"
                  rel="noopener noreferrer"
                  referrerPolicy="no-referrer"
                >
                  Review {scalar(record(row).sourceName ?? record(row).sourceKind)} externally (new
                  tab)
                </a>
              )}
              <History
                kind="provider_reputation_link"
                id={row.id}
                snapshotFields={[
                  "sourceKind",
                  "sourceName",
                  "url",
                  "notes",
                  "lastCheckedOn",
                  "archivedAt",
                ]}
              />
            </>
          )}
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

function reputationUrl(row: unknown): string | undefined {
  try {
    const url = new URL(scalar(record(row).url));
    return url.protocol === "https:" && !url.username && !url.password && !url.hash
      ? url.href
      : undefined;
  } catch {
    return undefined;
  }
}

function ProviderDirectory({ categories }: { categories: Category[] }) {
  const { scope } = useWorkspace();
  const [params, setParams] = useSearchParams();
  const [reset, setReset] = useState(0);
  const archive = params.get("archiveState"),
    selection = params.get("selectionStatus"),
    categoryState = params.get("categoryState");
  const result = useQuery({
    queryKey: scope.key("provider-directory", params.toString()),
    retry: false,
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
      <DynamicFilterForm
        key={reset}
        className="provider-directory-filters"
        aria-label="Provider filters"
        onReset={(event) => {
          event.preventDefault();
          setParams({}, { replace: true, preventScrollReset: true, flushSync: true });
          setReset((value) => value + 1);
        }}
        onSubmit={(event) => {
          event.preventDefault();
          const data = new FormData(event.currentTarget);
          const next = new URLSearchParams();
          if (params.has("propertyId")) next.set("propertyId", params.get("propertyId")!);
          for (const [key, value] of data)
            if (typeof value === "string" && value) next.set(key, value);
          setParams(next, { replace: true, preventScrollReset: true });
        }}
      >
        <label>
          Search providers
          <input
            type="search"
            name="q"
            placeholder="Search by name"
            defaultValue={params.get("q") ?? ""}
            maxLength={240}
          />
        </label>
        <label>
          Preference
          <select name="selectionStatus" defaultValue={selection ?? ""}>
            <option value="">Any</option>
            <option value="preferred">Preferred</option>
            <option value="neutral">No preference</option>
            <option value="avoid">Avoid</option>
          </select>
        </label>
        <label>
          Category
          <select
            key={categories.length}
            name="categoryId"
            defaultValue={params.get("categoryId") ?? ""}
          >
            <option value="">Any category</option>
            {categories
              .filter((category) => !category.archivedAt)
              .map((category) => (
                <option key={category.id} value={category.id}>
                  {category.displayName}
                </option>
              ))}
          </select>
        </label>
        <details className="provider-more-filters">
          <summary>More filters</summary>
          <div className="provider-filter-details">
            <label>
              Show providers
              <select name="archiveState" defaultValue={archive ?? "active"}>
                <option value="active">Active</option>
                <option value="archived">Archived</option>
                <option value="all">Active and archived</option>
              </select>
            </label>
            <label>
              Category assignment
              <select name="categoryState" defaultValue={categoryState ?? ""}>
                <option value="">Any</option>
                <option value="categorized">Has categories</option>
                <option value="uncategorized">No categories</option>
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
              Has references
            </label>
            <p className="provider-filter-hint">
              Service and service area must match a complete recorded label.
            </p>
          </div>
        </details>
        {params.has("propertyId") && (
          <p className="provider-filter-hint">
            Limited to providers with recorded work for the selected property. Clear filters to see
            other providers.
          </p>
        )}
        <button type="reset" className="provider-clear-filters">
          Clear filters
        </button>
      </DynamicFilterForm>
      {result.isPending && <p role="status">Loading providers…</p>}
      {result.error && (
        <p role="alert">
          {result.error.message}
          <button
            onClick={() => {
              const next = new URLSearchParams(params);
              next.delete("cursor");
              setParams(next, { preventScrollReset: true });
              if (!params.has("cursor")) void result.refetch();
            }}
          >
            Retry loading providers
          </button>
        </p>
      )}
      {result.data && (
        <>
          {result.data.items.length > 0 && (
            <p className="provider-directory-count">
              {result.data.items.length} {result.data.items.length === 1 ? "provider" : "providers"}{" "}
              on this page
            </p>
          )}
          {result.data.items.length === 0 && (
            <div className="provider-directory-empty">
              <h3>No providers found</h3>
              <p>Try another search or clear the filters.</p>
            </div>
          )}
          <ul className="provider-directory-grid">
            {result.data.items.map((item) => (
              <li key={item.party.id}>
                <Link
                  className="provider-directory-card"
                  aria-label={item.party.displayName}
                  state={{ returnTo: `/providers?${params}` }}
                  to={`/providers/${item.party.id}/details`}
                >
                  <div className="provider-card-heading">
                    <h3>{item.party.displayName}</h3>
                    <div className="provider-card-badges">
                      {item.profile.archivedAt && (
                        <span className="provider-card-badge">Archived</span>
                      )}
                      {item.profile.selectionStatus !== "neutral" && (
                        <span
                          className={`provider-card-badge provider-preference-${item.profile.selectionStatus}`}
                        >
                          {item.profile.selectionStatus === "preferred" ? "Preferred" : "Avoid"}
                        </span>
                      )}
                    </div>
                  </div>
                  <p className="provider-card-categories">
                    {item.categories.map((category) => category.displayName).join(" · ") ||
                      "No categories assigned"}
                  </p>
                  {(item.services.length > 0 || item.serviceAreas.length > 0) && (
                    <dl>
                      {item.services.length > 0 && (
                        <div>
                          <dt>Services</dt>
                          <dd>{item.services.map((service) => service.displayName).join(", ")}</dd>
                        </div>
                      )}
                      {item.serviceAreas.length > 0 && (
                        <div>
                          <dt>Service areas</dt>
                          <dd>{item.serviceAreas.map((area) => area.displayName).join(", ")}</dd>
                        </div>
                      )}
                    </dl>
                  )}
                  {item.profile.selectionStatus === "avoid" && item.profile.selectionReason && (
                    <p className="provider-card-caution">{item.profile.selectionReason}</p>
                  )}
                  <span className="provider-card-action">
                    View provider <span aria-hidden="true">→</span>
                  </span>
                </Link>
              </li>
            ))}
          </ul>
          <nav className="provider-directory-pagination" aria-label="Provider pages">
            {params.has("cursor") && (
              <button
                type="button"
                onClick={() => {
                  const next = new URLSearchParams(params);
                  next.delete("cursor");
                  setParams(next, { preventScrollReset: true });
                }}
              >
                Back to first page
              </button>
            )}
            {result.data.nextCursor && (
              <button
                onClick={() => {
                  const next = new URLSearchParams(params);
                  next.set("cursor", result.data?.nextCursor ?? "");
                  setParams(next, { preventScrollReset: true });
                }}
              >
                Next Providers
              </button>
            )}
          </nav>
        </>
      )}
    </section>
  );
}
