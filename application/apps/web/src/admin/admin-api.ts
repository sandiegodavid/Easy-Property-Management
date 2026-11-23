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
    state?: string;
    last_verified_at?: number | null;
    last_captured_at?: number | null;
    last_checked_at?: number | null;
    point_age_ms?: number | null;
    proof_ref?: string | null;
  }>;
  release_id: string;
  binding_id?: string | null;
  resource_generation?: number | null;
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
  operatorRevision?: number;
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

export interface AdminControlPoint {
  resource_id: string;
  revision?: number;
  state?: string;
  captured_at?: number | null;
  verified_at?: number | null;
  summary?: {
    captured_at?: number | null;
    verified_at?: number | null;
    admin_schema_revision?: string | null;
  } | null;
}

export interface AdminControlRecoveryStatus {
  mode: "normal" | "recovery";
  reason: string | null;
  activeAdminResourceRef: string | null;
  catalog: {
    items: AdminControlPoint[];
    freshness?: Freshness | null;
  };
}

export interface AdminControlPreview {
  previewId: string;
  pointId: string;
  deploymentId: string;
  sourceGeneration: number;
  selectedCapturedAt: number;
  selectedVerifiedAt: number;
  exactRequestHash: string;
  expiresAt: number;
}

export function formatProtectionLabel(protection: OperatorSummary["protection"]): {
  icon: string;
  label: string;
  detail: string | null;
} {
  const data = protection.data;
  if (!data) {
    return {
      icon: "!",
      label: protection.state === "unavailable" ? "Unavailable" : "Unknown",
      detail: protection.freshness?.error_code ?? null,
    };
  }
  const rawState = data.state ?? (data.status === "protected" ? "healthy" : "overdue");
  const asOf = data.last_verified_at ?? protection.freshness?.as_of ?? null;
  switch (rawState) {
    case "healthy":
      return {
        icon: "✓",
        label: "Protected",
        detail: asOf ? `Verified ${formatTimestamp(asOf)}` : null,
      };
    case "unchanged":
      return {
        icon: "✓",
        label: "Protected — unchanged",
        detail: asOf ? `Verified ${formatTimestamp(asOf)}` : null,
      };
    case "overdue":
    case "degraded":
      return {
        icon: "⚠",
        label: "Degraded",
        detail: asOf ? `Last verified ${formatTimestamp(asOf)}` : "Verification overdue",
      };
    case "unknown":
      return { icon: "?", label: "Unknown", detail: null };
    default:
      return { icon: "!", label: "Unavailable", detail: null };
  }
}

export function formatTimestamp(ms: number | null | undefined): string {
  if (typeof ms !== "number" || !Number.isFinite(ms)) return "Unavailable";
  return new Date(ms).toLocaleString();
}
