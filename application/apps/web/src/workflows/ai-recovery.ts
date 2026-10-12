import { useQuery } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { api } from "@epm/contracts";
import { useWorkspace } from "../app/workspace-gate";
import { recoveryApi, type Recovery, type RecoveryInput } from "../shared/recovery";
import { readResult } from "./reads";

type AiForm = Extract<RecoveryInput["formKey"], `ai.${string}`>;

/** OPS stores only allowlisted intent; credential bytes never enter this helper. */
export function useAiRecovery(draftId?: string) {
  const { scope } = useWorkspace();
  const [prepared, setPrepared] = useState<Recovery | null>(null);
  const preparedRef = useRef<Recovery | null>(null);
  const unresolved = useQuery({
    queryKey: scope.key("ai-unresolved", draftId ?? "settings"),
    queryFn: async ({ signal }) => {
      let cursor: string | undefined;
      do {
        const page = readResult(
          await api.GET("/api/operator/recovery", {
            signal,
            params: { query: { limit: 100, cursor } },
          }),
        );
        const item = page.items.find(
          (row) =>
            row.formKey.startsWith("ai.") &&
            row.status === "outcome_unknown" &&
            (draftId
              ? row.sourceKind === "ai_draft" && row.sourceId === draftId
              : row.sourceKind !== "ai_draft"),
        );
        if (item)
          return readResult(
            await api.GET("/api/operator/recovery/{record_id}", {
              signal,
              params: { path: { record_id: item.id } },
            }),
          );
        cursor = page.nextCursor ?? undefined;
      } while (cursor);
      return null;
    },
  });
  const current = prepared ?? unresolved.data ?? null;
  async function prepare(
    formKey: AiForm,
    sourceId: string | null,
    body: Record<string, unknown>,
    key: string,
  ) {
    if (unresolved.isFetching || unresolved.error || current || preparedRef.current)
      throw new Error("Resolve the original AI attempt before another command.");
    scope.requireWrite();
    const sourceKind =
      formKey === "ai.connection.create"
        ? null
        : formKey.startsWith("ai.draft.")
          ? "ai_draft"
          : formKey.startsWith("ai.connection.")
            ? "ai_connection"
            : formKey === "ai.settings.update"
              ? "ai_settings"
              : "ai_action_limit";
    const { idempotencyKey: omitted, ...payload } = body;
    void omitted;
    const revision = payload.version ?? payload.expectedRevision;
    const saved = await recoveryApi.save(key, {
      formKey,
      schemaVersion: 1,
      sourceKind,
      sourceId,
      baseSourceRevision: sourceKind ? String(revision) : null,
      payload,
      expectedRevision: 0,
      idempotencyKey: crypto.randomUUID(),
    });
    // Keep the saved identity even if preparation's response is interrupted.
    setPrepared({ ...saved, attemptKey: key });
    preparedRef.current = { ...saved, attemptKey: key };
    const result = await recoveryApi.prepare(key, {
      expectedRevision: saved.revision,
      idempotencyKey: key,
      attemptKey: key,
    });
    setPrepared(result);
    preparedRef.current = result;
  }
  async function reconcile() {
    const current = preparedRef.current ?? unresolved.data;
    if (!current) return;
    const latest = readResult(
      await api.GET("/api/operator/recovery/{record_id}", {
        params: { path: { record_id: current.id } },
      }),
    );
    const result = await recoveryApi.reconcile(current.id, {
      expectedRevision: latest.revision,
      idempotencyKey: crypto.randomUUID(),
    });
    if (result.status !== "reconciled") throw new Error("The original result is still unresolved.");
    setPrepared(null);
    preparedRef.current = null;
    await unresolved.refetch();
  }
  return {
    current,
    prepare,
    reconcile,
    blocked: unresolved.isFetching || !!unresolved.error || !!current,
  };
}
