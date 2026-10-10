export type ApiProblem = {
  code: string;
  message: string;
  fieldErrors: Record<string, string[]>;
  retryable: boolean;
  currentRevision?: string;
  correlationId?: string;
};

function object(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

export function normalizeApiError(status: number, value: unknown): ApiProblem {
  const outer = object(value);
  const detail = outer.detail ?? value;
  const data = object(detail);
  const fieldErrors: Record<string, string[]> = {};
  if (Array.isArray(detail)) {
    for (const entry of detail) {
      const issue = object(entry);
      if (Array.isArray(issue.loc) && typeof issue.msg === "string") {
        const field = issue.loc.filter((part) => part !== "body").join(".");
        (fieldErrors[field] ??= []).push(issue.msg);
      }
    }
  }
  for (const [field, errors] of Object.entries(object(data.fieldErrors))) {
    if (Array.isArray(errors) && errors.every((error) => typeof error === "string")) {
      fieldErrors[field] = errors;
    }
  }
  return {
    code: typeof data.code === "string" ? data.code : `http_${status}`,
    message:
      typeof data.message === "string"
        ? data.message
        : typeof detail === "string"
          ? detail
          : "The request could not be completed. Review your input and try again.",
    fieldErrors,
    retryable: status === 503,
    ...(typeof data.currentRevision === "string" || typeof data.currentRevision === "number"
      ? { currentRevision: String(data.currentRevision) }
      : {}),
    ...(typeof data.correlationId === "string" ? { correlationId: data.correlationId } : {}),
  };
}

export class MutationFailure extends Error {
  constructor(
    readonly problem: ApiProblem,
    readonly outcomeUnknown: boolean,
    readonly status = 0,
  ) {
    super(problem.message);
  }
}

// A transport error, cancellation or server failure cannot establish rollback.
export async function mutation<T>(
  request: () => Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  try {
    const result = await request();
    if (!result.response.ok || result.data === undefined) {
      throw new MutationFailure(
        normalizeApiError(result.response.status, result.error),
        result.response.status >= 500 || result.response.ok,
        result.response.status,
      );
    }
    return result.data;
  } catch (error) {
    if (error instanceof MutationFailure) throw error;
    throw new MutationFailure(
      {
        code: "outcome_unknown",
        message: "The response was interrupted. Reconcile the original attempt before continuing.",
        fieldErrors: {},
        retryable: false,
      },
      true,
    );
  }
}

// Stable bytes for detecting local edits; source-owned fingerprints come from OPS.
export function canonicalRequest(value: unknown): string {
  if (value === null || typeof value === "string" || typeof value === "boolean")
    return JSON.stringify(value);
  if (typeof value === "number" && Number.isFinite(value)) return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonicalRequest).join(",")}]`;
  if (typeof value === "object" && Object.getPrototypeOf(value) === Object.prototype) {
    const record = value as Record<string, unknown>;
    return `{${Object.keys(record)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${canonicalRequest(record[key])}`)
      .join(",")}}`;
  }
  throw new Error("Recovery accepts JSON fields only. Files and credentials need reselection.");
}
