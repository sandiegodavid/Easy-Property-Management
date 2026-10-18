import { api } from "@epm/contracts";
import { readResult } from "./reads";

export async function loadWorkflowResult(
  form: string,
  operation: string,
  key: string,
  signal: AbortSignal,
): Promise<unknown> {
  if (form.startsWith("portfolio."))
    return readResult(
      await api.GET("/api/portfolio/inventory-operations/{operation_id}", {
        signal,
        params: { path: { operation_id: operation } },
      }),
    ).result;
  if (form.startsWith("party."))
    return readResult(
      await api.GET("/api/parties/operations/{operation_id}", {
        signal,
        params: { path: { operation_id: operation } },
      }),
    );
  if (form.startsWith("tenant."))
    return readResult(
      await api.GET("/api/tenants/operations/{operation_id}", {
        signal,
        params: { path: { operation_id: operation } },
      }),
    );
  if (form.startsWith("provider.category."))
    return readResult(
      await api.GET("/api/provider-categories/operations/{operation_id}", {
        signal,
        params: { path: { operation_id: operation } },
      }),
    );
  if (form.startsWith("provider."))
    return readResult(
      await api.GET("/api/providers/operations/{operation_id}", {
        signal,
        params: { path: { operation_id: operation } },
      }),
    );
  if (form.startsWith("maintenance."))
    return readResult(
      await api.GET("/api/maintenance-command-receipts/{operation_id}", {
        signal,
        params: { path: { operation_id: operation } },
      }),
    ).response;
  if (form.startsWith("communication."))
    return readResult(
      await api.GET("/api/communications/operations/{operation_id}", {
        signal,
        params: { path: { operation_id: operation } },
      }),
    );
  if (form.startsWith("owner_concern."))
    return readResult(
      await api.GET("/api/owner-concerns/operations/by-key/{key}", {
        signal,
        params: { path: { key } },
      }),
    );
  if (form === "task.create")
    return readResult(
      await api.GET("/api/tasks/creation-operations/{key}", { signal, params: { path: { key } } }),
    );
  if (form.startsWith("task.waiting."))
    return readResult(
      await api.GET("/api/tasks/waiting-operations/{key}", { signal, params: { path: { key } } }),
    );
  if (form.startsWith("task."))
    return readResult(
      await api.GET("/api/tasks/mutation-operations/{key}", { signal, params: { path: { key } } }),
    );
  if (form.startsWith("intake."))
    return readResult(
      await api.GET("/api/intake/sources/operations/by-key/{idempotency_key}", {
        signal,
        params: { path: { idempotency_key: key } },
      }),
    );
  if (form.startsWith("lease."))
    return readResult(
      await api.GET("/api/leases/operations/{operation_id}", {
        signal,
        params: { path: { operation_id: operation } },
      }),
    ).response;
  if (form.startsWith("inspection."))
    return readResult(
      await api.GET("/api/inspection-commands/{operation_id}", {
        signal,
        params: { path: { operation_id: operation } },
      }),
    ).result;
  if (form === "file.upload")
    return readResult(
      await api.GET("/api/files/commands/by-key/{key}", { signal, params: { path: { key } } }),
    );
  if (form.startsWith("owner_rent_report."))
    return readResult(
      await api.GET("/api/owner-rent-report-operations/{key}", {
        signal,
        params: { path: { key } },
      }),
    ).result;
  if (form.startsWith("finance.expense_category."))
    return readResult(
      await api.GET("/api/expense-categories/operations/by-key/{key}", {
        signal,
        params: { path: { key } },
      }),
    );
  return readResult(
    await api.GET("/api/finance/command-operations/{idempotency_key}", {
      signal,
      params: { path: { idempotency_key: key } },
    }),
  ).result;
}
