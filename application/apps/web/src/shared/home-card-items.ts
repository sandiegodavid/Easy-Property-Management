import { useEffect } from "react";
import { useInfiniteQuery, type InfiniteData } from "@tanstack/react-query";
import { api } from "@epm/contracts";
import type { components } from "@epm/contracts/generated";
import { useWorkspace } from "../app/workspace-gate";

type Collection = components["schemas"]["AvailableCollection"];

// Continue the displayed capture, never substitute a fresh first page. Requests
// stay bounded to 100 rows; a changed/expired capture must be refreshed explicitly.
export function useHomeCardItems(
  collection: Collection | components["schemas"]["UnavailableCollection"] | undefined,
  enabled: boolean,
) {
  const { scope } = useWorkspace();
  const section = collection?.status === "available" ? collection : undefined;
  const query = useInfiniteQuery<
    Collection,
    Error,
    InfiniteData<Collection, string>,
    readonly unknown[],
    string
  >({
    queryKey: scope.key(
      "home-card-items",
      section?.collection,
      section?.capture.asOf,
      section?.capture.sourceRevision,
      section?.nextCursor,
    ),
    enabled: (current) => enabled && !!section?.nextCursor && current.state.status !== "error",
    initialPageParam: section?.nextCursor ?? "",
    retry: false,
    refetchOnWindowFocus: false,
    staleTime: Infinity,
    queryFn: async ({ pageParam, signal }) => {
      if (!section) throw new Error("Collection unavailable.");
      const response = await api.GET("/api/operator/home/items", {
        signal: AbortSignal.any([signal, AbortSignal.timeout(10_000)]),
        params: {
          query: {
            collection: section.collection,
            propertyId: section.viewAllTarget.scope.propertyId ?? undefined,
            horizonDays: section.viewAllTarget.horizonDays,
            limit: 100,
            cursor: pageParam,
          },
        },
      });
      const data = response.data;
      if (
        !data ||
        data.workspaceId !== scope.workspaceId ||
        data.runtimeEpoch !== scope.runtimeEpoch ||
        data.scope.kind !== section.viewAllTarget.scope.kind ||
        data.scope.propertyId !== section.viewAllTarget.scope.propertyId ||
        data.result.status !== "available" ||
        data.result.collection !== section.collection ||
        data.result.capture.asOf !== section.capture.asOf ||
        data.result.capture.sourceRevision !== section.capture.sourceRevision ||
        data.result.matchingTotal !== section.matchingTotal ||
        data.result.nextCursor === pageParam
      )
        throw new Error("Collection changed or is unavailable.");
      return data.result;
    },
    getNextPageParam: (page) => page.nextCursor ?? undefined,
  });
  const { hasNextPage, isFetching, isError, fetchNextPage } = query;
  useEffect(() => {
    if (enabled && hasNextPage && !isFetching && !isError) void fetchNextPage();
  }, [enabled, hasNextPage, isFetching, isError, fetchNextPage]);
  const seen = new Set(section?.items.map((item) => item.key));
  const items = (query.data?.pages.flatMap((page) => page.items) ?? []).filter((item) => {
    if (seen.has(item.key)) return false;
    seen.add(item.key);
    return true;
  });
  return {
    items: enabled ? items : [],
    loading: enabled && query.isFetching,
    failed: enabled && query.isError,
  };
}
