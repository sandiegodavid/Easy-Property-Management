import { useEffect, useRef } from "react";
import { Link, useLocation, useNavigate, resolvePath, type LinkProps } from "react-router-dom";
import type { ReactNode } from "react";
import { useWorkspace } from "../app/workspace-gate";
import { homeParams, type HomeFilters } from "./home-transport";
import type { components } from "@epm/contracts/generated";
import { record, workflows } from "@epm/contracts/workflows";
import { useQueryClient } from "@tanstack/react-query";

export const collections = [
  "needs_action",
  "waiting",
  "upcoming",
  "appointments",
  "information_review",
] as const;
export const collectionTitles = {
  needs_action: "Needs action",
  waiting: "Waiting",
  upcoming: "Upcoming",
  appointments: "Calendar and appointments",
  information_review: "Information review",
};

export function collectionUrl(
  section: components["schemas"]["AvailableCollection"],
  filters: HomeFilters,
) {
  const params = homeParams({
    ...filters,
    propertyId: section.viewAllTarget.scope.propertyId ?? undefined,
    horizonDays: section.viewAllTarget.horizonDays,
  });
  if (section.viewAllCursor) params.set("cursor", section.viewAllCursor);
  return `/home/collections/${section.collection}?${params}`;
}

export function HomeSourceLink({ to, children }: { to: string; children: ReactNode }) {
  const location = useLocation(),
    navigate = useNavigate();
  const { scope } = useWorkspace();
  const parent = useReturn();
  return (
    <Link
      to={to}
      onClick={(event) => {
        if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey)
          return;
        event.preventDefault();
        const returnTo = location.pathname + location.search;
        void navigate(to, {
          state: {
            returnTo,
            homeReturnTo: returnTo,
            homeReturnScroll: window.scrollY,
            homeRuntime: `${scope.workspaceId}:${scope.runtimeEpoch}`,
            rootReturnTo: parent?.href,
            rootReturnScroll: parent?.scroll,
          },
        });
      }}
    >
      {children}
    </Link>
  );
}

/** Carry validated Home context through owning detail/forms, without replacing
 * the owning workflow's own returnTo or saving evidence in browser storage. */
export function SourceWorkflowLink({ state, ...props }: LinkProps) {
  const navigationState = useSourceNavigationState();
  const navigate = useNavigate();
  const supplied: unknown = state;
  return (
    <Link
      {...props}
      state={supplied}
      onClick={(event) => {
        props.onClick?.(event);
        if (
          event.defaultPrevented ||
          event.button !== 0 ||
          event.metaKey ||
          event.ctrlKey ||
          event.shiftKey ||
          event.altKey ||
          props.reloadDocument ||
          (typeof props.to === "string" && /^(?:[a-z][a-z\d+.-]*:|\/\/)/i.test(props.to)) ||
          (props.target && props.target !== "_self")
        )
          return;
        event.preventDefault();
        void navigate(props.to, {
          state: navigationState(state, props.to),
          replace: props.replace,
          preventScrollReset: props.preventScrollReset,
          relative: props.relative,
        });
      }}
    />
  );
}

type Parent = { href: string; label: string; scroll: number };
function safePath(value: unknown): string | undefined {
  if (typeof value !== "string" || !value.startsWith("/") || value.startsWith("//")) return;
  const url = new URL(value, window.location.origin);
  if (url.origin === window.location.origin) return url.pathname + url.search + url.hash;
}
function pageIdentity(href: string) {
  const url = new URL(href, window.location.origin);
  const context = /^\/(properties|owners|providers|leases)\/[^/]+/.exec(url.pathname)?.[0];
  return (
    (context ?? url.pathname) +
    ["workflow", "target", "child", "record", "id", "identity", "file", "source"]
      .map((key) => `|${url.searchParams.get(key) ?? ""}`)
      .join("")
  );
}
function parentLabel(href: string) {
  const url = new URL(href, window.location.origin);
  const path = url.pathname;
  if (path === "/settings/provider-categories") return "Provider categories";
  if (path === "/settings/ai") return "AI assistance";
  if (path === "/settings/recovery") return "Unfinished forms";
  if (path === "/leasing" && url.searchParams.has("templates")) return "Inspection templates";
  if (path === "/conversations" && url.searchParams.get("intake") === "true")
    return "source directory";
  if (path === "/maintenance" && url.searchParams.get("tab") === "concerns")
    return "Owner concerns";
  if (url.searchParams.has("workflow"))
    return (
      workflows.find((item) => item.formKey === url.searchParams.get("workflow"))?.title ?? "form"
    );
  if (/^\/properties\//.test(path)) return "property";
  if (/^\/owners\//.test(path)) return "owner";
  if (/^\/leases\//.test(path)) return "lease";
  if (/^\/inspections\//.test(path)) return "inspection";
  if (url.searchParams.has("identity")) return path === "/tenants" ? "tenant" : "contact details";
  if (url.searchParams.has("record"))
    return (
      (
        {
          issue: "maintenance issue",
          task: "task",
          communication: "conversation",
          concern: "owner concern",
        } as Record<string, string>
      )[url.searchParams.get("record")!] ?? "money record"
    );
  return (
    (
      {
        properties: "Properties",
        owners: "Owners",
        tenants: "Tenants",
        parties: "Tenants",
        leasing: "Leasing",
        money: "Money",
        maintenance: "Maintenance",
        providers: "Providers",
        conversations: "Conversations",
        tasks: "Tasks",
        settings: "Settings",
        search: "Search",
        home: "Home",
      } as Record<string, string>
    )[path.split("/")[1]] ?? "parent page"
  );
}
function parents(state: unknown, runtime: string): Parent[] {
  if (
    !state ||
    typeof state !== "object" ||
    !("parentRuntime" in state) ||
    state.parentRuntime !== runtime ||
    !("parentTrail" in state) ||
    !Array.isArray(state.parentTrail)
  )
    return [];
  const entries: unknown[] = state.parentTrail;
  return entries
    .slice(-8)
    .filter(
      (item): item is Parent =>
        !!item &&
        typeof item === "object" &&
        "href" in item &&
        "label" in item &&
        "scroll" in item &&
        safePath(item.href) === item.href &&
        typeof item.label === "string" &&
        item.label.length <= 300 &&
        typeof item.scroll === "number" &&
        Number.isFinite(item.scroll) &&
        item.scroll >= 0,
    );
}

export function useSourceNavigationState() {
  const location = useLocation();
  const { scope } = useWorkspace();
  const client = useQueryClient();
  const back = useReturn();
  const runtime = `${scope.workspaceId}:${scope.runtimeEpoch}`;
  const context = back
    ? {
        homeReturnTo: back.href,
        homeReturnScroll: back.scroll,
        homeRuntime: back.runtime,
        rootReturnTo: back.parentHref,
        rootReturnScroll: back.parentScroll,
      }
    : {};
  return (supplied?: unknown, to?: LinkProps["to"]) => {
    const href = location.pathname + location.search + location.hash;
    const target = to ? resolvePath(to, location.pathname) : undefined;
    const samePage = target && pageIdentity(target.pathname + target.search) === pageIdentity(href);
    const trail = parents(location.state, runtime);
    if (!samePage) {
      const context = /^\/(properties|owners)\/([^/]+)/.exec(location.pathname);
      const name = context
        ? record(
            client.getQueryData(
              scope.key(
                context[1] === "properties" ? "portfolio-record" : "owner-identity",
                context[2],
              ),
            ),
          ).displayName
        : undefined;
      trail.push({
        href,
        label: typeof name === "string" && name.length <= 300 ? name : parentLabel(href),
        scroll: window.scrollY,
      });
    }
    return {
      ...context,
      parentRuntime: runtime,
      parentTrail: trail.slice(-8),
      ...(supplied && typeof supplied === "object" ? supplied : {}),
    };
  };
}

export function ParentBackLink({ to, children }: { to: string; children?: ReactNode }) {
  const location = useLocation();
  const { scope } = useWorkspace();
  const runtime = `${scope.workspaceId}:${scope.runtimeEpoch}`;
  const trail = parents(location.state, runtime).filter(
    (item) => pageIdentity(item.href) !== pageIdentity(location.pathname + location.search),
  );
  const parent = trail.at(-1);
  const value = location.state as Record<string, unknown> | null;
  const explicit =
    !value?.parentRuntime || value.parentRuntime === runtime
      ? safePath(value?.returnTo ?? value?.directory)
      : undefined;
  const fallback = safePath(to) ?? "/home";
  const href =
    parent?.href ??
    (explicit && pageIdentity(explicit) !== pageIdentity(location.pathname + location.search)
      ? explicit
      : fallback);
  const home = useReturn();
  return (
    <Link
      className="parent-back-link"
      to={href}
      state={{
        ...value,
        returnTo: undefined,
        directory: undefined,
        parentRuntime: runtime,
        parentTrail: trail.slice(0, -1),
        parentScroll: parent?.scroll,
        ...(home && href === home.href
          ? {
              homeScroll: home.scroll,
              homeRuntime: home.runtime,
              homeReturnTo: home.parentHref,
              homeReturnScroll: home.parentScroll,
            }
          : {}),
      }}
    >
      {pageIdentity(href) === pageIdentity(fallback) && children
        ? children
        : `← Back to ${parent?.label ?? parentLabel(href)}`}
    </Link>
  );
}

/** A scoped directory reached from a record is also a child page; sidebar visits have no trail. */
export function DirectoryParentReturn() {
  const location = useLocation();
  const { scope } = useWorkspace();
  const params = new URLSearchParams(location.search);
  if (
    ![
      "/properties",
      "/owners",
      "/tenants",
      "/leasing",
      "/money",
      "/maintenance",
      "/providers",
      "/conversations",
      "/tasks",
    ].includes(location.pathname) ||
    ["workflow", "record", "id", "identity", "file", "source", "templates"].some((key) =>
      params.has(key),
    ) ||
    params.get("intake") === "true"
  )
    return null;
  const fallback =
    location.pathname === "/money" && params.get("leaseId")
      ? `/leases/${params.get("leaseId")}/details`
      : location.pathname === "/money" && params.get("propertyId")
        ? `/properties/${params.get("propertyId")}/overview`
        : location.pathname === "/maintenance" && params.get("tab") === "concerns"
          ? "/maintenance"
          : undefined;
  const trail = parents(location.state, `${scope.workspaceId}:${scope.runtimeEpoch}`);
  return fallback || trail.length ? <ParentBackLink to={fallback ?? location.pathname} /> : null;
}

export function useParentScroll() {
  const location = useLocation();
  const { scope } = useWorkspace();
  useEffect(() => {
    const value = location.state as Record<string, unknown> | null;
    if (
      value?.parentRuntime !== `${scope.workspaceId}:${scope.runtimeEpoch}` ||
      typeof value.parentScroll !== "number" ||
      !Number.isFinite(value.parentScroll) ||
      value.parentScroll < 0
    )
      return;
    const scroll = value.parentScroll;
    const restore = () => window.scrollTo(0, scroll);
    const observer = new MutationObserver(restore);
    observer.observe(document.getElementById("workspace-content") ?? document.body, {
      childList: true,
      subtree: true,
    });
    const frame = requestAnimationFrame(restore);
    const timer = window.setTimeout(() => observer.disconnect(), 3000);
    const stop = () => observer.disconnect();
    window.addEventListener("wheel", stop, { once: true });
    window.addEventListener("touchstart", stop, { once: true });
    return () => {
      observer.disconnect();
      cancelAnimationFrame(frame);
      clearTimeout(timer);
      window.removeEventListener("wheel", stop);
      window.removeEventListener("touchstart", stop);
    };
  }, [location.key, location.state, scope.workspaceId, scope.runtimeEpoch]);
}

function useReturn() {
  const location = useLocation();
  const { scope } = useWorkspace();
  const value: unknown = location.state;
  if (
    !value ||
    typeof value !== "object" ||
    !("homeReturnTo" in value) ||
    !("homeReturnScroll" in value) ||
    !("homeRuntime" in value)
  )
    return;
  if (
    value.homeRuntime !== `${scope.workspaceId}:${scope.runtimeEpoch}` ||
    typeof value.homeReturnTo !== "string" ||
    typeof value.homeReturnScroll !== "number" ||
    !Number.isFinite(value.homeReturnScroll) ||
    value.homeReturnScroll < 0
  )
    return;
  if (!URL.canParse(value.homeReturnTo, window.location.origin)) return;
  const url = new URL(value.homeReturnTo, window.location.origin);
  if (
    url.origin !== window.location.origin ||
    !(
      url.pathname === "/home" ||
      url.pathname === "/home/inventory" ||
      collections.some((kind) => url.pathname === `/home/collections/${kind}`)
    )
  )
    return;
  return {
    href: url.pathname + url.search,
    scroll: value.homeReturnScroll,
    runtime: value.homeRuntime,
    parentHref:
      "rootReturnTo" in value && typeof value.rootReturnTo === "string"
        ? value.rootReturnTo
        : undefined,
    parentScroll:
      "rootReturnScroll" in value && typeof value.rootReturnScroll === "number"
        ? value.rootReturnScroll
        : undefined,
  };
}

export function HomeBackLink({ fallback, children }: { fallback: string; children: ReactNode }) {
  const back = useReturn();
  return (
    <Link
      to={back?.href ?? fallback}
      state={
        back
          ? {
              homeScroll: back.scroll,
              homeRuntime: back.runtime,
              homeReturnTo: back.parentHref,
              homeReturnScroll: back.parentScroll,
            }
          : undefined
      }
    >
      {children}
    </Link>
  );
}

export function HomeReturn() {
  const back = useReturn(),
    location = useLocation();
  if (!back || location.pathname.startsWith("/home")) return null;
  return <HomeBackLink fallback="/home">Return to Home collection or preview</HomeBackLink>;
}

export function useHomeScroll(loaded: boolean) {
  const location = useLocation(),
    { scope } = useWorkspace();
  const restored = useRef(false);
  const value: unknown = location.state;
  const position =
    value &&
    typeof value === "object" &&
    "homeScroll" in value &&
    typeof value.homeScroll === "number" &&
    "homeRuntime" in value &&
    value.homeRuntime === `${scope.workspaceId}:${scope.runtimeEpoch}`
      ? value.homeScroll
      : undefined;
  useEffect(() => {
    if (
      !loaded ||
      restored.current ||
      position === undefined ||
      !Number.isFinite(position) ||
      position < 0
    )
      return;
    const frame = requestAnimationFrame(() => {
      window.scrollTo(0, position);
      restored.current = true;
    });
    return () => cancelAnimationFrame(frame);
  }, [loaded, position]);
}
