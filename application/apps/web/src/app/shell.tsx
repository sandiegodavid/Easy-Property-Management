import { useEffect, useRef, useState } from "react";
import { AsyncRegion } from "@epm/ui";
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
      {title === "Home" && (
        <>
          <p>
            Hiding a destination does not hide its obligations. The Home work queue is not available
            yet.
          </p>
          <Link to="/tasks">Tasks</Link>
        </>
      )}
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
    return item && (!item.capability || bootstrap.capabilities.includes(item.capability))
      ? [item]
      : [];
  });
  const links = (
    <>
      <nav aria-label="Primary navigation">
        {ordered
          .filter((item) => !draft.hiddenDestinationIds.includes(item.id))
          .map((item) => (
            <NavLink key={item.id} to={item.route}>
              {item.label}
            </NavLink>
          ))}
      </nav>
      <details>
        <summary>More</summary>
        <nav aria-label="Hidden destinations">
          {ordered
            .filter((item) => draft.hiddenDestinationIds.includes(item.id))
            .map((item) => (
              <NavLink key={item.id} to={item.route}>
                {item.label}
              </NavLink>
            ))}
        </nav>
      </details>
    </>
  );
  return (
    <div className="shell">
      <a className="skip-link" href="#workspace-content">
        Skip to content
      </a>
      <aside>
        <div className="wide-nav">{links}</div>
        <details className="narrow-nav" ref={drawer}>
          <summary>Navigation</summary>
          {links}
        </details>
      </aside>
      <section className="workspace-body">
        <header>
          <p role="status">Local workspace connected.</p>
          <Link id="search-entry" to="/search">
            Search (Ctrl/⌘ K)
          </Link>
          <Link to="/settings/recovery">Unfinished forms</Link>
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
          {destinations.map((item) => (
            <Route key={item.id} element={<DestinationGuard id={item.id} />}>
              <Route
                path={item.route}
                element={
                  item.id === "settings" ? (
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
                    <PendingPage title={item.label} />
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
