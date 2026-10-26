import { api } from "@epm/contracts";
import type { components } from "@epm/contracts/generated";
import type { WorkspaceScope } from "../app/workspace-scope";
import { canonicalRequest, mutation, MutationFailure, type ApiProblem } from "./mutations";
import { hostedMode, hostedWritesAllowed } from "../app/hosted-session-state";

export type Recovery = components["schemas"]["RecoveryResponse"];
export type RecoveryInput = components["schemas"]["RecoveryInput"];
export type FormIdentity = Pick<
  RecoveryInput,
  "formKey" | "schemaVersion" | "sourceKind" | "sourceId" | "baseSourceRevision"
>;
type DraftState = "dirty" | "saving" | "saved" | "failed" | "conflicted";
type CommandState = "editing" | "submitting" | "committed" | "rejected" | "outcome_unknown";
type RecoverySnapshot = {
  editAuthority?: "held" | "required";
  draft: DraftState;
  command: CommandState;
  record?: Recovery;
  error?: string;
  problem?: ApiProblem;
};

export const recoveryApi = {
  save: (id: string, body: RecoveryInput, lease?: string) =>
    mutation(() =>
      api.PUT("/api/operator/recovery/{record_id}", {
        params: { path: { record_id: id } },
        body,
        headers: lease ? { "X-EPM-Draft-Lease": lease } : undefined,
      }),
    ),
  prepare: (id: string, body: components["schemas"]["AttemptInput"], lease?: string) =>
    mutation(() =>
      api.POST("/api/operator/recovery/{record_id}/attempt", {
        params: { path: { record_id: id } },
        body,
        headers: lease ? { "X-EPM-Draft-Lease": lease } : undefined,
      }),
    ),
  reconcile: (id: string, body: components["schemas"]["MutationInput"], lease?: string) =>
    mutation(() =>
      api.POST("/api/operator/recovery/{record_id}/reconcile", {
        params: { path: { record_id: id } },
        body,
        headers: lease ? { "X-EPM-Draft-Lease": lease } : undefined,
      }),
    ),
  returnToEditing: (id: string, body: components["schemas"]["MutationInput"], lease?: string) =>
    mutation(() =>
      api.POST("/api/operator/recovery/{record_id}/return", {
        params: { path: { record_id: id } },
        body,
        headers: lease ? { "X-EPM-Draft-Lease": lease } : undefined,
      }),
    ),
  discard: (id: string, body: components["schemas"]["MutationInput"], lease?: string) =>
    mutation(() =>
      api.POST("/api/operator/recovery/{record_id}/discard", {
        params: { path: { record_id: id } },
        body,
        headers: lease ? { "X-EPM-Draft-Lease": lease } : undefined,
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
  private pendingReturn?: components["schemas"]["MutationInput"];
  private active?: Promise<void>;
  private timer?: ReturnType<typeof setTimeout>;
  private disposed = false;
  private locked = false;
  private leaseToken?: string;
  private leaseExpires = 0;
  private leaseRenewed = 0;
  private lastInteraction = Date.now();
  private leaseRequest?: Promise<void>;
  private pendingClaim?: string;
  private pauseLease = () => {
    this.leaseToken = undefined;
    this.pendingClaim = undefined;
    this.publish({
      editAuthority:
        this.snapshot.record || this.pendingSave || this.pendingPrepare ? "required" : undefined,
    });
  };

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
      editAuthority: hostedMode() && recovered ? "required" : undefined,
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
  async claimEditing(takeover = false) {
    this.scope.requireWrite();
    if (this.leaseRequest) return this.leaseRequest;
    const bytes = crypto.getRandomValues(new Uint8Array(32));
    const token =
      this.pendingClaim ??
      btoa(String.fromCharCode(...bytes))
        .replaceAll("+", "-")
        .replaceAll("/", "_")
        .replaceAll("=", "");
    this.pendingClaim = token;
    this.leaseRequest = this.claimLease(token, takeover).finally(() => {
      this.leaseRequest = undefined;
    });
    return this.leaseRequest;
  }
  private async claimLease(token: string, takeover: boolean) {
    // A lost response may have advanced the durable revision. Read only the
    // authority revision; never replace/rebase an immutable pending operation.
    let revision = this.snapshot.record?.revision ?? 0;
    if (this.pendingSave || this.pendingPrepare) {
      const result = await this.readSavedForm();
      revision = result?.revision ?? 0;
    }
    await this.updateLease(token, takeover, false, revision);
  }
  private async updateLease(
    token: string,
    takeover: boolean,
    renew: boolean,
    expectedRevision = this.snapshot.record?.revision ?? 0,
  ) {
    try {
      const result = await mutation(() =>
        api.POST("/api/hosted/drafts/{record_id}/lease", {
          params: { path: { record_id: this.id } },
          body: { token, expectedRevision, takeover, renew },
        }),
      );
      this.scope.requireWrite();
      if (this.disposed) return;
      this.leaseToken = token;
      this.leaseExpires = Date.parse(result.expiresAt);
      this.leaseRenewed = Date.now();
      if (!renew) this.lastInteraction = Date.now();
      this.pendingClaim = undefined;
      this.publish({
        editAuthority: "held",
        error: undefined,
        ...(this.pendingSave && this.snapshot.draft === "conflicted" ? { draft: "failed" } : {}),
      });
    } catch (error) {
      if (error instanceof MutationFailure && !error.outcomeUnknown) this.pendingClaim = undefined;
      this.leaseToken = undefined;
      this.publish({
        editAuthority: "required",
        error: error instanceof Error ? error.message : "Claim editing before saving.",
      });
      throw error;
    }
  }
  async renewEditing() {
    if (
      !hostedMode() ||
      !this.leaseToken ||
      this.disposed ||
      this.leaseRequest ||
      !hostedWritesAllowed() ||
      document.visibilityState !== "visible" ||
      !document.hasFocus() ||
      Date.now() - this.lastInteraction > 60_000 ||
      Date.now() - this.leaseRenewed < 60_000
    )
      return;
    if (Date.now() >= this.leaseExpires) {
      this.leaseToken = undefined;
      this.publish({ editAuthority: "required" });
      return;
    }
    const token = this.leaseToken;
    this.leaseRequest = this.updateLease(token, false, true).finally(() => {
      this.leaseRequest = undefined;
    });
    await this.leaseRequest;
  }
  private async requireLease() {
    if (!hostedMode()) return;
    if (!this.leaseToken && !this.snapshot.record && this.snapshot.editAuthority !== "required")
      await this.claimEditing();
    if (!this.leaseToken || Date.now() >= this.leaseExpires) {
      this.publish({ editAuthority: "required" });
      throw new Error(
        "Claim editing or explicitly take over this saved form before saving. Your input is retained.",
      );
    }
  }
  private async readSavedForm() {
    const result = await api.GET("/api/operator/recovery/{record_id}", {
      params: { path: { record_id: this.id } },
    });
    this.scope.requireWrite();
    if (this.disposed) throw new Error("Form was closed. Reload its recovery record.");
    if (result.response.status === 404) return undefined;
    if (!result.data || result.error) throw new Error("The latest saved form could not be read.");
    return result.data;
  }
  async reviewSavedForm() {
    const record = await this.readSavedForm();
    if (this.pendingSave || this.pendingPrepare) {
      this.publish({
        error:
          "Claim editing, then retry the original save or check submission. Your input is retained.",
      });
      return;
    }
    if (!record) throw new Error("The latest saved form could not be read.");
    this.reviewLatest(record, record.baseSourceRevision);
  }
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
  private checkAuthority(error: unknown) {
    if (
      error instanceof MutationFailure &&
      ["hosted_draft_lease_conflict", "hosted_draft_revision_conflict"].includes(error.problem.code)
    ) {
      this.leaseToken = undefined;
      this.publish({ editAuthority: "required" });
    }
  }
  private accept(record: Recovery) {
    this.scope.requireWrite();
    if (this.disposed) throw new Error("Form was closed. Reload its recovery record.");
    this.scope.client.setQueryData(this.scope.key("recovery", this.id), record);
    this.publish({ record });
  }
  edit(payload: Record<string, unknown>, delay = 500) {
    this.lastInteraction = Date.now();
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
        await this.requireLease();
        const result = await this.transport.save(this.id, body, this.leaseToken);
        this.accept(result);
        this.pendingSave = undefined;
        this.acknowledged = canonicalRequest(body.payload);
        this.publish({
          draft: canonicalRequest(this.payload) === this.acknowledged ? "saved" : "dirty",
        });
      } catch (error) {
        this.checkAuthority(error);
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
        await this.requireLease();
        prepared = await this.transport.prepare(this.id, this.pendingPrepare, this.leaseToken);
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
      this.checkAuthority(error);
      // Once prepared, even a rejection stays locked until the owning receipt resolves it.
      if (
        error instanceof MutationFailure &&
        !error.outcomeUnknown &&
        [400, 404, 409, 412, 413, 422].includes(error.status) &&
        this.snapshot.record?.status === "outcome_unknown"
      ) {
        try {
          await this.returnToEditing();
        } catch {
          // Closing may itself have an unknown outcome. Keep the immutable request protected.
        }
      }
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
    } catch (error) {
      this.checkAuthority(error);
      throw error;
    } finally {
      this.locked = false;
    }
  }

  async returnToEditing() {
    if (this.active) await this.active;
    await this.requireLease();
    const current = this.snapshot.record;
    if (!current || current.status !== "outcome_unknown")
      throw new Error("Check the current submission first.");
    this.pendingReturn ??= {
      expectedRevision: current.revision,
      idempotencyKey: crypto.randomUUID(),
    };
    const result = await this.transport.returnToEditing(
      this.id,
      this.pendingReturn,
      this.leaseToken,
    );
    this.accept(result);
    this.pendingReturn = undefined;
    this.pendingPrepare = undefined;
    this.pendingReconcile = undefined;
    this.acknowledged = canonicalRequest(result.payload);
    this.publish({ command: "editing", draft: "saved", error: undefined, problem: undefined });
  }
  private async reconcileAttempt() {
    this.scope.requireWrite();
    await this.requireLease();
    if (this.pendingPrepare) {
      this.accept(await this.transport.prepare(this.id, this.pendingPrepare, this.leaseToken));
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
      result = await this.transport.reconcile(this.id, this.pendingReconcile, this.leaseToken);
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
    if (this.snapshot.command === "outcome_unknown") {
      try {
        await this.reconcile();
        throw new Error(
          "This submission succeeded. Open its result; discarding input does not delete the record.",
        );
      } catch (error) {
        if (!(error instanceof MutationFailure) || error.status !== 409) throw error;
        await this.returnToEditing();
      }
    }
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
        await this.requireLease();
        this.pendingDiscard ??= {
          expectedRevision: this.snapshot.record.revision,
          idempotencyKey: crypto.randomUUID(),
        };
        this.accept(await this.transport.discard(this.id, this.pendingDiscard, this.leaseToken));
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
    window.removeEventListener("epm-session-paused", this.pauseLease);
  }
  activate() {
    this.disposed = false;
    window.addEventListener("epm-session-paused", this.pauseLease);
    if (
      hostedMode() &&
      this.snapshot.record &&
      this.scope.canWrite &&
      this.snapshot.command !== "committed"
    ) {
      void this.claimEditing().catch(() => undefined);
    }
  }
}
