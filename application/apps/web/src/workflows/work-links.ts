export type WorkKind = "issue" | "communication" | "task" | "concern";
export function workUrl(kind: WorkKind, id: string) {
  return `${kind === "task" ? "/tasks" : kind === "communication" ? "/conversations" : "/maintenance"}?record=${kind}&id=${id}`;
}
