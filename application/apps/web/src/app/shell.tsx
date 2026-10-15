import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { AsyncRegion } from "@epm/ui";
import { api } from "@epm/contracts";
import { useQuery } from "@tanstack/react-query";
import {
  createBrowserRouter,
  createRoutesFromElements,
  RouterProvider,
  Link,
  NavLink,
  Navigate,
  Outlet,
  Route,
  useLocation,
  useParams,
  useSearchParams,
} from "react-router-dom";
import { useWorkspace } from "./workspace-gate";
import {
  destinations,
  destination,
  ownerSections,
  propertySections,
  contextPath,
} from "./destinations";
import { PreferencesProvider, PreferenceSettings, usePreferences } from "./preferences";
import { RecoveryPage } from "../shared/recovery-page";
import { Directory, ContextOverview, ContextNavigator } from "../shared/context-reads";
import { PortfolioCommand, PortfolioEntry, PortfolioRecord } from "../workflows/portfolio";
import { IdentityWorkspace } from "../workflows/identity";
import { ProviderWorkspace } from "../workflows/providers";
import { LeasingWorkspace } from "../workflows/leasing";
import { InspectionWorkspace } from "../workflows/inspections";
import { MoneyWorkspace } from "../workflows/money";
import { WorkWorkspace } from "../workflows/work";
import { MetadataSearch } from "../shared/search";
import { CoveragePage, CoverageResume } from "../shared/coverage";
import { AiDraftReview, AiGovernanceSettings } from "../workflows/ai-governance";
import { Home } from "../shared/home";
import { HomeCollectionPage } from "../shared/home-collection-page";
import { HomeInventoryPage } from "../shared/home-inventory-page";
import { HomeReturn } from "../shared/home-navigation";

function NavigationIcon({ kind }: { kind: (typeof destinations)[number]["icon"] }) {
  const paths = {
    home: "m3 10 9-7 9 7v10H3Zm6 10v-8h6v8",
    building: "M4 21V3h12v18M16 9h4v12M8 7h4M8 11h4M8 15h4M8 21v-3h4v3",
    people:
      "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M22 21v-2a4 4 0 0 0-3-3.87M16 3a4 4 0 0 1 0 8M13 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0",
    key: "M15 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0M11 11v10M11 17h4M11 21h3",
    wallet: "M20 8V4H4v16h16v-5M4 8h18v8h-7V8",
    tools: "m14 6 4 4M4 20l8-8M14 3l-3 3 7 7 3-3M3 15l6 6",
    settings:
      "M9 3h6l1 3 3 1 2 5-2 5-3 1-1 3H9l-1-3-3-1-2-5 2-5 3-1ZM16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0",
  };
  return (
    <svg
      className="navigation-icon"
      viewBox="0 0 24 24"
      width="17"
      height="17"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={paths[kind]} />
    </svg>
  );
}

function SidebarNavigation({
  items,
  hiddenIds,
  bounded = false,
}: {
  items: readonly (typeof destinations)[number][];
  hiddenIds: readonly string[];
  bounded?: boolean;
}) {
  const container = useRef<HTMLDivElement>(null);
  const measurement = useRef<HTMLDivElement>(null);
  const [layout, setLayout] = useState({ count: items.length, overflowHeight: 0 });
  const visible = items.filter((item) => !hiddenIds.includes(item.id));
  const hidden = items.filter((item) => hiddenIds.includes(item.id));
  useLayoutEffect(() => {
    if (!bounded) return;
    const root = container.current;
    const measure = measurement.current;
    if (!root || !measure) return;
    function resize() {
      if (!root || !measure || root.clientHeight === 0) return;
      const heights = Array.from(measure.children, (child) => child.getBoundingClientRect().height);
      const moreHeight = heights.pop() ?? 0;
      const gap = parseFloat(getComputedStyle(measure).rowGap) || 0;
      const fullHeight =
        heights.reduce((sum, height) => sum + height, 0) + Math.max(0, heights.length - 1) * gap;
      let count = heights.length;
      let overflowHeight = 0;
      if (fullHeight > root.clientHeight || hidden.length > 0) {
        // Reserve room for More and its scrollable contents, even while collapsed.
        const reserve = Math.min(root.clientHeight * 0.4, (heights[0] ?? moreHeight) * 3);
        let used = 0;
        count = 0;
        for (const height of heights) {
          const next = used + (count ? gap : 0) + height;
          if (next + moreHeight + reserve > root.clientHeight) break;
          used = next;
          count += 1;
        }
        overflowHeight = Math.max(0, root.clientHeight - used - moreHeight);
      }
      setLayout((previous) =>
        previous.count === count && previous.overflowHeight === overflowHeight
          ? previous
          : { count, overflowHeight },
      );
    }
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(root);
    observer.observe(measure);
    return () => observer.disconnect();
  }, [bounded, items, hidden.length]);
  const count = bounded ? layout.count : visible.length;
  const remaining = [...visible.slice(count), ...hidden];
  const link = (item: (typeof destinations)[number]) => (
    <NavLink key={item.id} to={item.route}>
      <NavigationIcon kind={item.icon} />
      {item.label}
    </NavLink>
  );
  return (
    <div className="sidebar-navigation" ref={container}>
      {bounded && (
        <div className="navigation-measure" ref={measurement} aria-hidden="true">
          {visible.map((item) => (
            <span className="navigation-measure-item" key={item.id}>
              <NavigationIcon kind={item.icon} />
              {item.label}
            </span>
          ))}
          <span className="navigation-measure-item">&nbsp;</span>
        </div>
      )}
      <nav aria-label="Primary navigation">{visible.slice(0, count).map(link)}</nav>
      {remaining.length > 0 && (
        <details className="more-destinations">
          <summary>More</summary>
          <nav
            aria-label="Hidden destinations"
            style={bounded ? { maxHeight: layout.overflowHeight } : undefined}
          >
            {remaining.map(link)}
          </nav>
        </details>
      )}
    </div>
  );
}

function LeasingPage() {
  const [params] = useSearchParams();
  return params.get("workflow")?.startsWith("inspection.") ||
    params.get("workflow") === "file.link.archive" ||
    params.has("templates") ? (
    <InspectionWorkspace key={params.toString()} />
  ) : (
    <LeasingWorkspace key={params.toString()} />
  );
}

function PropertiesPage() {
  const [params] = useSearchParams();
  return params.has("workflow") ? (
    <PortfolioCommand key={params.toString()} />
  ) : (
    <>
      <PortfolioEntry />
      <Directory kind="property" />
    </>
  );
}
function PropertyDetails({ tab }: { tab: string }) {
  const { id = "" } = useParams();
  return (
    <>
      <PortfolioRecord id={id} />
      <ContextOverview kind="property" tab={tab} />
    </>
  );
}
function WorkflowPage({ kind }: { kind: "provider" | "identity" }) {
  const [params] = useSearchParams();
  const location = useLocation();
  const key = `${location.pathname}:${params.get("workflow")}:${params.get("target")}:${params.get("child")}:${params.get("resume")}`;
  return kind === "provider" ? <ProviderWorkspace key={key} /> : <IdentityWorkspace key={key} />;
}

function PendingPage({ title }: { title: string }) {
  const [params, setParams] = useSearchParams();
  return (
    <>
      <h2>{title}</h2>
      {["propertyId", "ownerId"].map(
        (key) =>
          params.get(key) && (
            <p key={key}>
              {key === "propertyId" ? "Property" : "Owner"} filter: {params.get(key)}{" "}
              <button
                onClick={() => {
                  const next = new URLSearchParams(params);
                  next.delete(key);
                  next.delete("cursor");
                  setParams(next);
                }}
              >
                Remove {key === "propertyId" ? "property" : "owner"} filter
              </button>
            </p>
          ),
      )}
      <AsyncRegion
        title={`${title} availability`}
        state={{
          kind: "unavailable",
          message: "This workflow is scheduled for a later UI slice. No records have been loaded.",
        }}
      />
      {title === "Maintenance" && <Link to="/providers">Providers</Link>}
    </>
  );
}

function Unavailable() {
  return (
    <>
      <h2>Page unavailable</h2>
      <p>
        This route or capability is not available in the current interface. UI-002 proposal review
        and legal engagements are not enabled.
      </p>
      <Link to="/home">Return Home</Link>
    </>
  );
}
function DestinationGuard({ id }: { id: string }) {
  const { bootstrap } = useWorkspace();
  const target = destination(id);
  return target && (!target.capability || bootstrap.capabilities.includes(target.capability)) ? (
    <Outlet />
  ) : (
    <Unavailable />
  );
}
function ContextWorkspace({ kind }: { kind: "property" | "owner" }) {
  const { id = "" } = useParams();
  const [params] = useSearchParams();
  const location = useLocation();
  const sections = kind === "property" ? propertySections : ownerSections;
  const navigationState: unknown = location.state;
  if (contextPath({ kind, id }) === "/home") return <Unavailable />;
  return (
    <section>
      <h2>{kind === "property" ? "Property" : "Owner"} workspace</h2>
      <p>{id}</p>
      <ContextNavigator key={`${kind}:${id}`} kind={kind} />
      <nav aria-label={`${kind} sections`}>
        {sections.map((section) => (
          <NavLink key={section} state={navigationState} to={`${section}?${params.toString()}`}>
            {section}
          </NavLink>
        ))}
      </nav>
      <Link
        to={`/money?${kind === "property" ? "propertyId" : "ownerId"}=${encodeURIComponent(id)}`}
      >
        View in Money
      </Link>
      <Outlet />
    </section>
  );
}
function Layout() {
  const { bootstrap, scope } = useWorkspace();
  const backup = useQuery({
    queryKey: scope.key("sidebar-backup-status"),
    queryFn: async ({ signal }) => {
      const result = await api.GET("/api/workspace/backup-status", { signal });
      if (!result.data || result.error) throw new Error("Backup status is unavailable.");
      return result.data;
    },
    staleTime: 60_000,
    refetchInterval: 60_000,
    retry: false,
  });
  const { draft } = usePreferences();
  const location = useLocation();
  const drawer = useRef<HTMLDetailsElement>(null);
  const content = useRef<HTMLElement>(null);
  useEffect(() => {
    if (drawer.current) drawer.current.open = false;
    content.current?.focus();
    document.title = `${destination(location.pathname.split("/")[1] ?? "")?.label ?? "Workspace"} · Easy Property Management`;
  }, [location.pathname]);
  useEffect(() => {
    function shortcut(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        document.getElementById("search-entry")?.focus();
      }
    }
    document.addEventListener("keydown", shortcut);
    return () => document.removeEventListener("keydown", shortcut);
  }, []);
  const ordered = draft.destinationOrder.flatMap((id) => {
    const item = destination(id);
    return item &&
      item.id !== "settings" &&
      (!item.capability || bootstrap.capabilities.includes(item.capability))
      ? [item]
      : [];
  });
  return (
    <div className="shell">
      <a className="skip-link" href="#workspace-content">
        Skip to content
      </a>
      <aside>
        <div className="wide-nav">
          <SidebarNavigation items={ordered} hiddenIds={draft.hiddenDestinationIds} bounded />
        </div>
        <details className="narrow-nav" ref={drawer}>
          <summary>Navigation</summary>
          <SidebarNavigation items={ordered} hiddenIds={draft.hiddenDestinationIds} />
        </details>
        <div className="sidebar-footer">
          <NavLink to="/settings">
            <NavigationIcon kind="settings" />
            Settings
          </NavLink>
          <div className="sidebar-status" aria-label="Workspace and backup status">
            <p role="status">Local workspace connected.</p>
            <p role="status">
              {backup.isError
                ? "Backup status unavailable"
                : !backup.data
                  ? "Checking backup status…"
                  : backup.data.needsAttention
                    ? "Backup needs attention"
                    : !backup.data.lastSuccessAt
                      ? "No successful backup yet"
                      : "Last backup"}
              {backup.data?.lastSuccessAt && !backup.isError && (
                <>
                  {" · "}
                  <time dateTime={backup.data.lastSuccessAt}>
                    {new Date(backup.data.lastSuccessAt).toLocaleString(undefined, {
                      dateStyle: "short",
                      timeStyle: "short",
                    })}
                  </time>
                </>
              )}
            </p>
          </div>
        </div>
      </aside>
      <section className="workspace-body">
        <header className="workspace-toolbar">
          <Link id="search-entry" to="/search">
            Search (Ctrl/⌘ K)
          </Link>
          <Link to="/settings/recovery">Unfinished forms</Link>
          <HomeReturn />
        </header>
        {!scope.canWrite && <p>Workspace writes are unavailable.</p>}
        {(bootstrap.preferencesState !== "available" || !bootstrap.preferences) && (
          <p>Appearance and navigation preferences are unavailable. Using display defaults.</p>
        )}
        <section id="workspace-content" tabIndex={-1} ref={content}>
          <Outlet />
        </section>
      </section>
    </div>
  );
}

export function ApplicationShell() {
  const [router] = useState(() =>
    createBrowserRouter(
      createRoutesFromElements(
        <Route element={<Layout />}>
          <Route index element={<Navigate to="/home" replace />} />
          <Route element={<DestinationGuard id="home" />}>
            <Route path="/home/collections/:collection" element={<HomeCollectionPage />} />
            <Route path="/home/inventory" element={<HomeInventoryPage />} />
          </Route>
          {destinations.map((item) => (
            <Route key={item.id} element={<DestinationGuard id={item.id} />}>
              <Route
                path={item.route}
                element={
                  item.id === "home" ? (
                    <Home />
                  ) : item.id === "settings" ? (
                    <Outlet />
                  ) : item.id === "properties" ? (
                    <PropertiesPage />
                  ) : item.id === "owners" ? (
                    <Directory kind="owner" />
                  ) : item.id === "providers" ? (
                    <WorkflowPage kind="provider" />
                  ) : item.id === "leasing" ? (
                    <LeasingPage />
                  ) : item.id === "money" ? (
                    <MoneyWorkspace />
                  ) : item.id === "maintenance" ? (
                    <WorkWorkspace />
                  ) : (
                    <Unavailable />
                  )
                }
              >
                {item.id === "settings" && (
                  <>
                    <Route index element={<PreferenceSettings />} />
                    <Route path="recovery" element={<RecoveryPage />} />
                    {["appearance", "navigation"].map((section) => (
                      <Route key={section} path={section} element={<PreferenceSettings />} />
                    ))}
                    <Route path="workspace" element={<PendingPage title="Workspace settings" />} />
                    <Route path="ai" element={<AiGovernanceSettings />} />
                    <Route path="provider-categories" element={<ProviderWorkspace catalogOnly />} />
                  </>
                )}
              </Route>
            </Route>
          ))}
          {(["property", "owner"] as const).map((kind) => (
            <Route
              key={kind}
              element={<DestinationGuard id={kind === "property" ? "properties" : "owners"} />}
            >
              <Route
                path={`${kind === "property" ? "/properties" : "/owners"}/:id`}
                element={<ContextWorkspace kind={kind} />}
              >
                <Route index element={<Navigate to="overview" replace />} />
                {(kind === "property" ? propertySections : ownerSections).map((section) => (
                  <Route
                    key={section}
                    path={section}
                    element={
                      kind === "property" && ["details", "units"].includes(section) ? (
                        <PropertyDetails tab={section} />
                      ) : section === "documents" ? (
                        <PendingPage title={section} />
                      ) : (
                        <ContextOverview kind={kind} tab={section} />
                      )
                    }
                  />
                ))}
              </Route>
            </Route>
          ))}
          <Route element={<DestinationGuard id="providers" />}>
            <Route path="providers/:id" element={<WorkflowPage kind="provider" />} />
            <Route path="providers/:id/:section" element={<WorkflowPage kind="provider" />} />
          </Route>
          <Route path="parties" element={<WorkflowPage kind="identity" />} />
          <Route element={<DestinationGuard id="leasing" />}>
            <Route path="leases/:id" element={<LeasingPage />} />
            <Route path="leases/:id/:section" element={<LeasingPage />} />
            <Route path="inspections/:id" element={<InspectionWorkspace />} />
          </Route>
          <Route path="tasks" element={<WorkWorkspace kind="task" />} />
          <Route path="tasks/:id" element={<WorkWorkspace kind="task" />} />
          <Route path="conversations" element={<WorkWorkspace kind="communication" />} />
          <Route path="maintenance/issues/:id" element={<WorkWorkspace />} />
          <Route path="search" element={<MetadataSearch />} />
          <Route path="ai/review/:id" element={<AiDraftReview />} />
          <Route path="coverage/:kind/:id/:area" element={<CoveragePage />} />
          <Route path="coverage/reviews/:id" element={<CoverageResume />} />
          <Route path="*" element={<Unavailable />} />
        </Route>,
      ),
    ),
  );
  return (
    <PreferencesProvider>
      <RouterProvider router={router} />
    </PreferencesProvider>
  );
}
