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
                    <Directory kind="property" />
                  ) : item.id === "owners" ? (
                    <Directory kind="owner" />
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
                    {["workspace", "ai"].map((section) => (
                      <Route
                        key={section}
                        path={section}
                        element={
                          <PendingPage
                            title={section === "ai" ? "AI assistance" : "Workspace settings"}
                          />
                        }
                      />
                    ))}
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
                      section === "documents" ? (
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
          {["tasks", "search"].map((path) => (
            <Route
              key={path}
              path={path}
              element={<PendingPage title={path === "tasks" ? "Tasks" : "Search"} />}
            />
          ))}
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
