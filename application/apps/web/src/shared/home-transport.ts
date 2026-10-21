import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "@epm/contracts";
import type { components, paths } from "@epm/contracts/generated";
import { useWorkspace } from "../app/workspace-gate";
import { usePreferences } from "../app/preferences";
import { readResult } from "../workflows/reads";

type Schemas = components["schemas"];
export type Attention =
  paths["/api/operator/home/attention"]["get"]["responses"][200]["content"]["application/json"];
export type HomeFilters = {
  propertyId?: string;
  horizonDays: 7 | 30 | 90;
  fromOn: string;
  throughOn: string;
};
export type HomeRead<T> = {
  kind: "unavailable" | "loading" | "failed" | "available";
  value?: T;
  message?: string;
  status?: number;
  updating: boolean;
  /** A source command or elapsed refresh window made this read stale. */
  stale: boolean;
  elapsed: number;
  retry: () => void;
};

async function deadline<T>(signal: AbortSignal, load: (signal: AbortSignal) => Promise<T>) {
  const timeout = new AbortController();
  const timer = window.setTimeout(() => timeout.abort(), 10000);
  try {
    const value = await load(AbortSignal.any([signal, timeout.signal]));
    if (timeout.signal.aborted) throw new Error("Home read timed out. Retry when ready.");
    return value;
  } catch (error) {
    if (timeout.signal.aborted) throw new Error("Home read timed out. Retry when ready.");
    throw error;
  } finally {
    window.clearTimeout(timer);
  }
}

function useElapsed(fetching: boolean) {
  const [wait, setWait] = useState({ fetching, seconds: 0 });
  if (wait.fetching !== fetching) setWait({ fetching, seconds: 0 });
  useEffect(() => {
    if (!fetching) return;
    const started = performance.now();
    const timer = window.setInterval(
      () =>
        setWait((current) => ({
          ...current,
          seconds: Math.floor((performance.now() - started) / 1000),
        })),
      1000,
    );
    return () => window.clearInterval(timer);
  }, [fetching]);
  return wait.seconds;
}

function calendarDate(value: string | null): value is string {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const instant = new Date(value + "T00:00:00Z");
  return Number.isFinite(instant.getTime()) && instant.toISOString().slice(0, 10) === value;
}

export function homeFilters(params: URLSearchParams, serverTime: string): HomeFilters {
  const instant = new Date(serverTime);
  if (!Number.isFinite(instant.getTime())) throw new Error("Server calendar is unavailable.");
  const month = instant.toISOString().slice(0, 7);
  const last = new Date(instant.getTime());
  last.setUTCMonth(last.getUTCMonth() + 1, 0);
  const from = params.get("fromOn"),
    through = params.get("throughOn");
  const validPeriod = calendarDate(from) && calendarDate(through) && from <= through;
  const property = params.get("propertyId")?.trim().toLowerCase();
  const horizon = params.get("horizonDays");
  return {
    propertyId:
      property && /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(property)
        ? property
        : undefined,
    horizonDays: horizon === "30" ? 30 : horizon === "90" ? 90 : 7,
    fromOn: validPeriod ? from : month + "-01",
    throughOn: validPeriod ? through : last.toISOString().slice(0, 10),
  };
}

export function homeParams(filters: HomeFilters) {
  const params = new URLSearchParams();
  if (filters.propertyId) params.set("propertyId", filters.propertyId);
  params.set("horizonDays", String(filters.horizonDays));
  params.set("fromOn", filters.fromOn);
  params.set("throughOn", filters.throughOn);
  return params;
}

function admitted<
  T extends
    | Schemas["HomeResponse"]
    | Attention
    | Schemas["CollectionResponse"]
    | Schemas["HomeInventoryResponse"],
>(value: T, workspaceId: string, epoch: string, propertyId?: string): T {
  if (
    value.contractVersion !== 1 ||
    value.workspaceId !== workspaceId ||
    value.runtimeEpoch !== epoch ||
    (value.scope.propertyId ?? undefined) !== propertyId ||
    value.scope.kind !== (propertyId ? "property" : "portfolio")
  ) {
    throw new Error("Home response no longer matches this workspace and scope. Refresh to retry.");
  }
  return value;
}

function useRead<T>(
  ready: boolean,
  key: readonly unknown[],
  load: (signal: AbortSignal) => Promise<T>,
  options?: { refreshDelay?: (value: T | undefined) => number | false; interval?: number },
): HomeRead<T> {
  const query = useQuery<T>({
    queryKey: key,
    enabled: ready,
    retry: false,
    // Home reads refresh while visible; continuation pages retain their capture.
    refetchOnWindowFocus: options?.refreshDelay ? "always" : false,
    refetchInterval: options?.refreshDelay
      ? (current) => options.refreshDelay?.(current.state.data) ?? false
      : false,
    refetchIntervalInBackground: false,
    staleTime: options?.refreshDelay ? (options.interval ?? 300_000) : 0,
    queryFn: ({ signal }) => deadline(signal, load),
  });
  const { refetch } = query;
  useEffect(() => {
    if (!options?.refreshDelay) return;
    const refreshOnReturn = () => {
      if (document.visibilityState === "visible") void refetch({ cancelRefetch: false });
    };
    const refreshWhenVisible = () => {
      if (document.visibilityState === "visible") refreshOnReturn();
    };
    window.addEventListener("focus", refreshOnReturn);
    document.addEventListener("visibilitychange", refreshWhenVisible);
    return () => {
      window.removeEventListener("focus", refreshOnReturn);
      document.removeEventListener("visibilitychange", refreshWhenVisible);
    };
  }, [options?.refreshDelay, refetch]);
  const elapsed = useElapsed(query.isFetching);
  return {
    kind: !ready ? "unavailable" : query.error ? "failed" : query.data ? "available" : "loading",
    value: query.data,
    message: query.error?.message,
    status: query.error instanceof HomePageFailure ? query.error.status : undefined,
    updating: query.isFetching,
    stale: query.isStale,
    elapsed,
    retry: () => {
      void query.refetch({ cancelRefetch: false });
    },
  };
}

function liveRefreshDelay(value: Attention | undefined, interval: number) {
  const transition = value?.nextTransitionAt ? Date.parse(value.nextTransitionAt) : Number.NaN;
  if (!Number.isFinite(transition)) return interval;
  // Keep the configured check, but never wait past a source-declared
  // follow-up/deadline transition. A small floor avoids an immediate retry loop
  // while the server publishes the next transition.
  return Math.min(interval, Math.max(1_000, transition - Date.now()));
}

class HomePageFailure extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

export function useHomeItems(
  collection: Schemas["Collection"],
  filters: HomeFilters,
  limit: number,
  cursor?: string,
) {
  const { scope, bootstrap } = useWorkspace();
  return useRead(
    bootstrap.capabilities.includes("operator.home"),
    scope.key(
      "home-items",
      collection,
      filters.propertyId ?? null,
      filters.horizonDays,
      limit,
      cursor ?? null,
    ),
    async (signal) => {
      const result = await api.GET("/api/operator/home/items", {
        signal,
        params: {
          query: {
            collection,
            propertyId: filters.propertyId,
            horizonDays: filters.horizonDays,
            limit,
            cursor,
          },
        },
      });
      if (!result.data) {
        try {
          readResult(result);
        } catch (error) {
          throw new HomePageFailure(
            result.response.status,
            error instanceof Error ? error.message : "Collection unavailable.",
          );
        }
        throw new HomePageFailure(result.response.status, "Collection unavailable.");
      }
      const value = admitted(
        result.data,
        scope.workspaceId,
        scope.runtimeEpoch,
        filters.propertyId,
      );
      if (value.result.collection !== collection)
        throw new Error("Collection response no longer matches this view.");
      return value;
    },
  );
}

export function useHomeReads(filters: HomeFilters) {
  const { scope, bootstrap } = useWorkspace();
  const { homeRefreshMinutes } = usePreferences();
  const interval = homeRefreshMinutes * 60_000;
  const ready = bootstrap.capabilities.includes("operator.home");
  const full = useRead(
    ready,
    scope.key(
      "home",
      filters.propertyId ?? null,
      filters.horizonDays,
      filters.fromOn,
      filters.throughOn,
    ),
    async (signal) =>
      admitted(
        readResult(
          await api.GET("/api/operator/home", {
            signal,
            params: { query: { ...filters, limitPerSection: 5 } },
          }),
        ),
        scope.workspaceId,
        scope.runtimeEpoch,
        filters.propertyId,
      ),
    { interval, refreshDelay: () => interval },
  );
  const live = useRead(
    ready,
    scope.key("home-attention", filters.propertyId ?? null),
    async (signal) =>
      admitted(
        readResult(
          await api.GET("/api/operator/home/attention", {
            signal,
            params: { query: { propertyId: filters.propertyId, limit: 5 } },
          }),
        ),
        scope.workspaceId,
        scope.runtimeEpoch,
        filters.propertyId,
      ),
    { interval, refreshDelay: (value) => liveRefreshDelay(value, interval) },
  );
  return {
    full,
    live,
    refresh: () => {
      full.retry();
      live.retry();
    },
  };
}

export function useHomeInventory(
  occupancy: "vacant" | "unknown",
  propertyId: string | undefined,
  limit: number,
  cursor?: string,
) {
  const { scope, bootstrap } = useWorkspace();
  return useRead(
    bootstrap.capabilities.includes("operator.home"),
    scope.key("home-inventory", occupancy, propertyId ?? null, limit, cursor ?? null),
    async (signal) => {
      const result = await api.GET("/api/operator/home/inventory", {
        signal,
        params: { query: { occupancy, propertyId, limit, cursor } },
      });
      if (!result.data) {
        try {
          readResult(result);
        } catch (error) {
          throw new HomePageFailure(
            result.response.status,
            error instanceof Error ? error.message : "Inventory unavailable.",
          );
        }
        throw new HomePageFailure(result.response.status, "Inventory unavailable.");
      }
      const value = admitted(result.data, scope.workspaceId, scope.runtimeEpoch, propertyId);
      if (value.occupancy !== occupancy || value.propertyState !== "active")
        throw new Error("Inventory response no longer matches this view.");
      return value;
    },
  );
}
