import { api } from "@epm/contracts";
import { readResult } from "../workflows/reads";

export async function partyNames(
  ids: string[],
  signal?: AbortSignal,
): Promise<Map<string, string>> {
  const unique = [...new Set(ids)];
  const names = new Map<string, string>();
  for (let offset = 0; offset < unique.length; offset += 100) {
    const rows = readResult(
      await api.GET("/api/parties/names", {
        signal,
        params: { query: { ids: unique.slice(offset, offset + 100) } },
      }),
    );
    for (const row of rows) names.set(row.id, row.displayName);
  }
  return names;
}
