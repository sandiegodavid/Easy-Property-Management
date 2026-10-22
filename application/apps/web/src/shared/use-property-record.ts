import { useQuery } from "@tanstack/react-query";
import { api } from "@epm/contracts";
import { useWorkspace } from "../app/workspace-gate";
import { readResult } from "../workflows/reads";

export function usePropertyRecord(id: string, enabled = true) {
  const { scope } = useWorkspace();
  return useQuery({
    queryKey: scope.key("portfolio-record", id),
    enabled: enabled && !!id,
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/properties/{property_id}", {
          signal,
          params: { path: { property_id: id } },
        }),
      ),
  });
}
