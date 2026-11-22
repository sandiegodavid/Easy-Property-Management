export interface AdminSession {
  expiresAt: number;
  recentAuthRequired?: boolean;
  csrfToken?: string;
}

export interface Freshness {
  state: "known" | "stale" | "unknown" | "unavailable";
  as_of?: number | null;
  source_revision?: string | null;
  error_code?: string | null;
}

export interface Section<T> {
  state: "loading" | "ready" | "refreshing" | "stale" | "failed" | "unavailable";
  data?: T | null;
  freshness?: Freshness | null;
}

export interface ActionState {
  action: string;
  enabled: boolean;
  reason?: string | null;
}

export interface OperationOutcome {
  operation: {
    operation_id: string;
    kind: string;
    idempotency_key: string;
  };
  state: string;
  revision: number;
  observed_at: number;
  error_code?: string | null;
}

export interface OperatorSummary {
  operator_id: string;
  workspace_id: string;
  display_name: string;
  slug: string;
  setup_state: string;
  desired_enabled: boolean;
  access: Section<{ effective_enabled: boolean }>;
  usage: Section<{ plan: "free"; usable_bytes: number; used_bytes: number }>;
  protection: Section<{
    status: "protected" | "degraded";
    last_verified_at?: number | null;
    point_age_ms?: number | null;
    proof_ref?: string | null;
  }>;
  release_id: string;
  operation?: OperationOutcome | null;
  actions: ActionState[];
}

export interface AdminListResponse {
  directory: Section<{
    items: OperatorSummary[];
    matching_total: number | null;
    freshness: Freshness;
  }>;
  nextCursor?: string | null;
  actions: ActionState[];
}

export interface ReadinessGate {
  name: string;
  state: "passed" | "pending" | "failed" | "unavailable";
  evidence_ref?: string | null;
}

export interface AdminDetailResponse {
  operator: OperatorSummary;
  readiness: Section<{
    state: "pending" | "ready" | "failed" | "unavailable";
    checks: ReadinessGate[];
  }>;
  refresh_operation?: OperationOutcome | null;
  actions: ActionState[];
}

export interface AdminBootstrapResponse {
  deploymentId: string;
  publicBaseDomain: string;
  loginOrigin: string;
  registryGeneration: number;
  freePolicy: {
    policy_id: string;
    plan_code: string;
    policy_version: number;
    usable_bytes: number;
  } | null;
  qualifiedOperatorReleases: {
    release_id: string;
    artifact_ref: string;
    artifact_digest: string;
    qualified_at: number;
  }[];
  admissionCommitment: Record<string, unknown> | null;
  capacity: {
    available: boolean;
    profileRef?: string;
    profileRevision?: number;
    snapshotRevision?: number;
    observedAt?: number;
    commitmentCount?: number;
  };
}

export interface IssuedInvitationResponse {
  outcome: OperationOutcome;
  invitationId: string | null;
  token: string | null;
  expiresAt: number | null;
}

export class AdminApiError extends Error {
  code: string;
  status: number;
  limitingResources: string[];

  constructor(code: string, message: string, status: number, limitingResources: string[] = []) {
    super(message);
    this.code = code;
    this.status = status;
    this.limitingResources = limitingResources;
  }
}

export async function adminFetch<T>(
  path: string,
  options?: { method?: "GET" | "POST"; body?: object; csrf?: string },
): Promise<T> {
  const method = options?.method ?? (options?.body ? "POST" : "GET");
  const response = await fetch(path, {
    signal: AbortSignal.timeout(10_000),
    method,
    credentials: "same-origin",
    headers: {
      ...(options?.body ? { "Content-Type": "application/json" } : {}),
      ...(options?.csrf ? { "X-CSRF-Token": options.csrf } : {}),
    },
    body: options?.body ? JSON.stringify(options.body) : undefined,
  });
  const parsed = (await response.json().catch(() => ({}))) as {
    code?: string;
    message?: string;
    limitingResources?: string[];
  };
  if (!response.ok) {
    throw new AdminApiError(
      parsed.code ?? "request_failed",
      parsed.message ?? "The request could not be completed.",
      response.status,
      parsed.limitingResources ?? [],
    );
  }
  return parsed as T;
}

export function formatMegabytes(bytes: number): string {
  return `${(bytes / 1_000_000).toFixed(2)} MB`;
}

export function formatTimestamp(ms: number | null | undefined): string {
  if (typeof ms !== "number" || !Number.isFinite(ms)) return "Unavailable";
  return new Date(ms).toLocaleString();
}
