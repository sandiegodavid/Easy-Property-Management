import { useQuery } from "@tanstack/react-query";
import { api } from "@epm/contracts";
import { scalar, type Workflow } from "@epm/contracts/workflows";
import { useSearchParams } from "react-router-dom";
import { useWorkspace } from "../app/workspace-gate";
import { readResult } from "./reads";

export function useWorkflowRecovery(definition: Workflow | undefined) {
  const [params] = useSearchParams();
  const { scope } = useWorkspace();
  const resume = params.get("resume");
  const recovery = useQuery({
    queryKey: scope.key("workflow-recovery", resume),
    enabled: !!resume,
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/operator/recovery/{record_id}", {
          signal,
          params: { path: { record_id: resume! } },
        }),
      ),
  });
  const child =
    params.get("child") ??
    (definition?.childKey && recovery.data
      ? scalar(recovery.data.payload[definition.childKey])
      : undefined);

  return { resume, recovery, child };
}
