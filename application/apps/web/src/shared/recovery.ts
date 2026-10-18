import { api } from "@epm/contracts";
import type { components } from "@epm/contracts/generated";
import type { WorkspaceScope } from "../app/workspace-scope";
import { canonicalRequest, mutation, MutationFailure, type ApiProblem } from "./mutations";

export type Recovery = components["schemas"]["RecoveryResponse"];
export type RecoveryInput = components["schemas"]["RecoveryInput"];
export type FormIdentity = Pick<
  RecoveryInput,
  "formKey" | "schemaVersion" | "sourceKind" | "sourceId" | "baseSourceRevision"
>;
type DraftState = "dirty" | "saving" | "saved" | "failed" | "conflicted";
type CommandState = "editing" | "submitting" | "committed" | "rejected" | "outcome_unknown";
type RecoverySnapshot = {
  draft: DraftState;
  command: CommandState;
  record?: Recovery;
  error?: string;
  problem?: ApiProblem;
};

export const recoveryApi = {
  save: (id: string, body: RecoveryInput) =>
    mutation(() =>
      api.PUT("/api/operator/recovery/{record_id}", { params: { path: { record_id: id } }, body }),
    ),
  prepare: (id: string, body: components["schemas"]["AttemptInput"]) =>
    mutation(() =>
      api.POST("/api/operator/recovery/{record_id}/attempt", {
        params: { path: { record_id: id } },
        body,
      }),
    ),
  reconcile: (id: string, body: components["schemas"]["MutationInput"]) =>
    mutation(() =>
      api.POST("/api/operator/recovery/{record_id}/reconcile", {
        params: { path: { record_id: id } },
        body,
      }),
    ),
  discard: (id: string, body: components["schemas"]["MutationInput"]) =>
    mutation(() =>
      api.POST("/api/operator/recovery/{record_id}/discard", {
        params: { path: { record_id: id } },
        body,
      }),
    ),
};

/** One mounted form owns edits; Query owns acknowledged remote representations.
 * Caller supplies a registered allowlisted payload, never a whole form/DOM object.
 * No localStorage: OPS is the durable recovery store, including across restore.
 */
export class RecoveryController {
  private snapshot: RecoverySnapshot;
  private listeners = new Set<() => void>();
  private payload: Record<string, unknown>;
  private readonly initialPayload: string;
  private acknowledged: string;
  private pendingSave?: RecoveryInput;
  private pendingPrepare?: components["schemas"]["AttemptInput"];
  private pendingReconcile?: components["schemas"]["MutationInput"];
  private pendingDiscard?: components["schemas"]["MutationInput"];
  private active?: Promise<void>;
  private timer?: ReturnType<typeof setTimeout>;
  private disposed = false;
  private locked = false;

  constructor(
    private readonly scope: WorkspaceScope,
    readonly id: string,
    private readonly identity: FormIdentity,
    initial: Record<string, unknown>,
    recovered?: Recovery,
    private readonly transport = recoveryApi,
  ) {
    this.initialPayload = canonicalRequest(initial);
    this.payload = JSON.parse(this.initialPayload) as Record<string, unknown>;
    this.acknowledged = recovered ? canonicalRequest(recovered.payload) : "";
    this.snapshot = {
      draft: recovered ? "saved" : "dirty",
      command:
        recovered?.status === "outcome_unknown"
          ? "outcome_unknown"
          : recovered?.receipt
            ? "committed"
            : "editing",
      record: recovered,
    };
  }

  getSnapshot = () => this.snapshot;
  get isPristine() {
    return (
      !this.snapshot.record &&
      this.snapshot.command === "editing" &&
      !this.active &&
      !this.pendingSave &&
      !this.pendingPrepare &&
      !this.pendingDiscard &&
      canonicalRequest(this.payload) === this.initialPayload
    );
  }
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };
  private publish(change: Partial<RecoverySnapshot>) {
    this.snapshot = { ...this.snapshot, ...change };
    for (const listener of this.listeners) listener();
  }
  private accept(record: Recovery) {
    this.scope.requireWrite();
    if (this.disposed) throw new Error("Form was closed. Reload its recovery record.");
    this.scope.client.setQueryData(this.scope.key("recovery", this.id), record);
    this.publish({ record });
  }
  edit(payload: Record<string, unknown>, delay = 500) {
    if (
      this.locked ||
      this.snapshot.command === "outcome_unknown" ||
      this.snapshot.command === "committed" ||
      (this.snapshot.record && this.snapshot.record.status !== "active") ||
      this.pendingSave ||
      this.pendingDiscard ||
      this.snapshot.draft === "conflicted"
    )
      throw new Error("Resolve the current attempt or conflict before editing.");
    this.scope.requireWrite();
    this.payload = JSON.parse(canonicalRequest(payload)) as Record<string, unknown>;
    this.publish({
      draft: canonicalRequest(this.payload) === this.acknowledged ? "saved" : "dirty",
      error: undefined,
    });
    clearTimeout(this.timer);
    this.timer = setTimeout(() => {
      void this.flush().catch(() => undefined);
    }, delay);
  }

  flush(): Promise<void> {
    clearTimeout(this.timer);
    if (this.active) return this.active;
    this.active = this.saveLoop().finally(() => {
      this.active = undefined;
    });
    return this.active;
  }
  private async saveLoop() {
    if (this.snapshot.draft === "conflicted") throw new Error("Review latest before saving.");
    while (this.pendingSave || canonicalRequest(this.payload) !== this.acknowledged) {
      this.scope.requireWrite();
      if (this.disposed || this.snapshot.command === "outcome_unknown")
        throw new Error("Form is unavailable.");
      const body = this.pendingSave ?? {
        ...this.identity,
        payload: this.payload,
        expectedRevision: this.snapshot.record?.revision ?? 0,
        idempotencyKey: crypto.randomUUID(),
      };
      this.publish({ draft: "saving", error: undefined });
      try {
        const result = await this.transport.save(this.id, body);
        this.accept(result);
        this.pendingSave = undefined;
        this.acknowledged = canonicalRequest(body.payload);
        this.publish({
          draft: canonicalRequest(this.payload) === this.acknowledged ? "saved" : "dirty",
        });
      } catch (error) {
        if (error instanceof MutationFailure && error.outcomeUnknown) this.pendingSave = body;
        this.publish({
          draft:
            error instanceof MutationFailure && [409, 412].includes(error.status)
              ? "conflicted"
              : "failed",
          error: error instanceof Error ? error.message : "Save failed.",
          problem: error instanceof MutationFailure ? error.problem : undefined,
        });
        throw error;
      }
    }
  }

  /** Explicit review preserves local edits; background queries never call this. */
  reviewLatest(record: Recovery, baseSourceRevision: string | null) {
    if (
      this.pendingSave ||
      this.pendingPrepare ||
      record.status !== "active" ||
      record.reuseState !== "available"
    )
      throw new Error("Reconcile this record before reuse.");
    this.identity.baseSourceRevision = baseSourceRevision;
    this.accept(record);
    this.acknowledged = canonicalRequest(record.payload);
    this.publish({ draft: "dirty", error: undefined });
  }

  /** Explicit operator review of a newly read owning-source revision. OPS rechecks
   * it during save and preparation; an unresolved attempt can never be rebased. */
  reviewSource(current: Recovery | undefined, revision: number, field: string) {
    if (
      this.locked ||
      this.pendingSave ||
      this.pendingPrepare ||
      this.pendingReconcile ||
      this.pendingDiscard ||
      this.snapshot.command === "outcome_unknown" ||
      this.snapshot.command === "committed" ||
      (current && current.status !== "active") ||
      (this.snapshot.record && !current)
    )
      throw new Error("Resolve the original attempt before reviewing another revision.");
    if (!Number.isInteger(revision) || revision < 0)
      throw new Error("Invalid displayed source revision.");
    this.identity.baseSourceRevision = String(revision);
    if (current) this.accept(current);
    this.payload = { ...this.payload, [field]: revision };
    this.acknowledged = current ? canonicalRequest(current.payload) : "";
    this.publish({ draft: "dirty", command: "editing", error: undefined, problem: undefined });
  }

  async submit(dispatch: (record: Recovery) => Promise<unknown>, fingerprint?: string) {
    if (
      this.locked ||
      this.snapshot.command === "outcome_unknown" ||
      this.snapshot.command === "committed"
    )
      throw new Error("Reconcile the original attempt first.");
    if (this.pendingDiscard) throw new Error("Resolve discard before submitting.");
    this.locked = true;
    try {
      await this.flush();
      this.scope.requireWrite();
      const current = this.snapshot.record;
      if (!current || current.reuseState !== "available")
        throw new Error("Review the source before submitting.");
      this.pendingPrepare ??= {
        expectedRevision: current.revision,
        idempotencyKey: crypto.randomUUID(),
        attemptKey: crypto.randomUUID(),
        requestFingerprint: fingerprint,
      };
      this.publish({ command: "submitting", error: undefined });
      let prepared: Recovery;
      try {
        prepared = await this.transport.prepare(this.id, this.pendingPrepare);
      } catch (error) {
        if (error instanceof MutationFailure && !error.outcomeUnknown)
          this.pendingPrepare = undefined;
        throw error;
      }
      this.accept(prepared);
      this.pendingPrepare = undefined;
      await dispatch(prepared);
      await this.reconcileAttempt();
    } catch (error) {
      // Once prepared, even a rejection stays locked until the owning receipt resolves it.
      this.publish({
        command:
          this.pendingPrepare || this.snapshot.record?.status === "outcome_unknown"
            ? "outcome_unknown"
            : "rejected",
        error: error instanceof Error ? error.message : "Command failed.",
        problem: error instanceof MutationFailure ? error.problem : undefined,
      });
      throw error;
    } finally {
      this.locked = false;
    }
  }

  async reconcile() {
    if (this.locked) throw new Error("A request is already running.");
    this.locked = true;
    try {
      await this.reconcileAttempt();
    } finally {
      this.locked = false;
    }
  }
  private async reconcileAttempt() {
    this.scope.requireWrite();
    if (this.pendingPrepare) {
      this.accept(await this.transport.prepare(this.id, this.pendingPrepare));
      this.pendingPrepare = undefined;
    }
    const current = this.snapshot.record;
    if (!current || current.status !== "outcome_unknown") throw new Error("No unresolved attempt.");
    this.pendingReconcile ??= {
      expectedRevision: current.revision,
      idempotencyKey: crypto.randomUUID(),
    };
    let result: Recovery;
    try {
      result = await this.transport.reconcile(this.id, this.pendingReconcile);
    } catch (error) {
      if (error instanceof MutationFailure && !error.outcomeUnknown)
        this.pendingReconcile = undefined;
      throw error;
    }
    this.pendingReconcile = undefined;
    this.accept(result);
    this.publish({ command: "committed", error: undefined });
  }

  /** Explicit replay uses only the immutable prepared payload and original key. */
  async replay(dispatch: (record: Recovery) => Promise<unknown>) {
    if (this.locked) throw new Error("A request is already running.");
    this.locked = true;
    try {
      this.scope.requireWrite();
      const current = this.snapshot.record;
      if (!current?.attemptKey || current.status !== "outcome_unknown" || this.pendingPrepare)
        throw new Error("Reconcile preparation first.");
      await dispatch(current);
      await this.reconcileAttempt();
    } finally {
      this.locked = false;
    }
  }
  async discard() {
    if (
      this.locked ||
      this.pendingSave ||
      this.pendingPrepare ||
      this.snapshot.command === "outcome_unknown"
    )
      throw new Error("Resolve pending writes before discarding.");
    clearTimeout(this.timer);
    this.locked = true;
    try {
      await this.active;
      this.scope.requireWrite();
      if (this.snapshot.record) {
        this.pendingDiscard ??= {
          expectedRevision: this.snapshot.record.revision,
          idempotencyKey: crypto.randomUUID(),
        };
        this.accept(await this.transport.discard(this.id, this.pendingDiscard));
        this.pendingDiscard = undefined;
      }
      this.acknowledged = canonicalRequest(this.payload);
      this.publish({ draft: "saved" });
    } catch (error) {
      if (error instanceof MutationFailure && !error.outcomeUnknown)
        this.pendingDiscard = undefined;
      this.publish({
        draft: "failed",
        error: error instanceof Error ? error.message : "Discard failed.",
      });
      throw error;
    } finally {
      this.locked = false;
    }
  }
  async beforeNavigate() {
    await this.flush();
    return this.snapshot.draft === "saved" && !this.pendingPrepare && !this.pendingDiscard;
  }
  dispose() {
    this.disposed = true;
    clearTimeout(this.timer);
  }
  activate() {
    this.disposed = false;
  }
}
