import { useEffect, useRef } from "react";
import { Link, useLocation, useNavigate, type LinkProps } from "react-router-dom";
import type { ReactNode } from "react";
import { useWorkspace } from "../app/workspace-gate";
import { homeParams, type HomeFilters } from "./home-transport";
import type { components } from "@epm/contracts/generated";

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
  const back = useReturn();
  const supplied: unknown = state;
  const context = back
    ? {
        homeReturnTo: back.href,
        homeReturnScroll: back.scroll,
        homeRuntime: back.runtime,
        rootReturnTo: back.parentHref,
        rootReturnScroll: back.parentScroll,
      }
    : {};
  return (
    <Link
      {...props}
      state={{ ...context, ...(supplied && typeof supplied === "object" ? supplied : {}) }}
    />
  );
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
