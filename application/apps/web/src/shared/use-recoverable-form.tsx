import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { useForm, type DefaultValues, type FieldValues } from "react-hook-form";
import { useBlocker, useNavigate } from "react-router-dom";
import { useWorkspace } from "../app/workspace-gate";
import { RecoveryController, type FormIdentity, type Recovery } from "./recovery";
import { hostedMode } from "../app/hosted-session-state";

/** Mount with key={workspace/runtime/form identity}. Background queries must not
 * reset defaultValues. Recovery projections explicitly select registered fields.
 */
export function useRecoverableForm<T extends FieldValues>({
  id,
  identity,
  initial,
  recovered,
  project,
}: {
  id: string;
  identity: FormIdentity;
  initial: DefaultValues<T>;
  recovered?: Recovery;
  project: (values: T) => Record<string, unknown>;
}) {
  const { scope } = useWorkspace();
  const form = useForm<T>({ defaultValues: initial });
  const [controller] = useState(
    () => new RecoveryController(scope, id, identity, project(form.getValues()), recovered),
  );
  const state = useSyncExternalStore(controller.subscribe, controller.getSnapshot);
  useEffect(() => {
    controller.activate();
    const timer = setInterval(() => {
      void controller.renewEditing().catch(() => undefined);
    }, 60_000);
    return () => {
      clearInterval(timer);
      controller.dispose();
    };
  }, [controller]);
  const navigationBlocked =
    !controller.isPristine && (state.draft !== "saved" || state.command === "submitting");
  const blocker = useBlocker(() => {
    const current = controller.getSnapshot();
    return (
      !controller.isPristine && (current.draft !== "saved" || current.command === "submitting")
    );
  });
  useEffect(() => {
    return form.subscribe({
      formState: { values: true },
      callback: ({ values }) => controller.edit(project(values)),
    });
  }, [controller, form, project]);
  useEffect(() => {
    if (!navigationBlocked) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [navigationBlocked]);
  return { form, controller, state, blocker };
}

function BlockedNavigation({
  controller,
  blocker,
}: {
  controller: RecoveryController;
  blocker: ReturnType<typeof useBlocker>;
}) {
  const [error, setError] = useState<string>();
  const [pending, setPending] = useState(false);
  const origin = useRef<HTMLElement | null>(null);
  const firstAction = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (blocker.state !== "blocked") return;
    origin.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    firstAction.current?.focus();
  }, [blocker.state]);
  if (blocker.state !== "blocked") return null;
  const leave = async (discard: boolean) => {
    setPending(true);
    try {
      if (discard) await controller.discard();
      else if (!(await controller.beforeNavigate())) return;
      blocker.proceed();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not save the draft.");
    } finally {
      setPending(false);
    }
  };
  return (
    <section aria-label="Unfinished form">
      <p>Save this unfinished form before leaving, or explicitly discard your edits.</p>
      {error && <p role="alert">{error}</p>}
      <button
        ref={firstAction}
        disabled={pending}
        onClick={() => {
          void leave(false);
        }}
      >
        Save and leave
      </button>
      <button
        disabled={pending}
        onClick={() => {
          void leave(true);
        }}
      >
        Discard and leave
      </button>
      <button
        disabled={pending}
        onClick={() => {
          blocker.reset();
          if (origin.current?.isConnected) origin.current.focus();
        }}
      >
        Keep editing
      </button>
    </section>
  );
}

export function RecoveryNavigation(props: {
  controller: RecoveryController;
  blocker: ReturnType<typeof useBlocker>;
  showActions?: boolean;
}) {
  const { scope } = useWorkspace();
  const navigate = useNavigate();
  const state = useSyncExternalStore(props.controller.subscribe, props.controller.getSnapshot);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string>();
  async function perform(operation: () => Promise<unknown>) {
    setBusy(true);
    setActionError(undefined);
    try {
      await operation();
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : "Could not complete this action.";
      if (props.controller.getSnapshot().error !== message) setActionError(message);
    } finally {
      setBusy(false);
    }
  }

  const claim = async (takeover: boolean) => {
    setBusy(true);
    try {
      await props.controller.claimEditing(takeover);
    } catch {
      /* The controller retains input and publishes the typed conflict. */
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      {props.showActions !== false && !["committed", "submitting"].includes(state.command) && (
        <div className="result-card-actions">
          {state.command !== "outcome_unknown" && (
            <button
              type="button"
              disabled={busy || !scope.canWrite}
              onClick={() => {
                void perform(async () => {
                  await props.controller.flush();
                  await navigate("/settings/recovery");
                });
              }}
            >
              Save and close
            </button>
          )}
          <button
            type="button"
            disabled={busy || !scope.canWrite}
            onClick={() => {
              if (
                !window.confirm(
                  "Discard this unfinished form? Existing official records will not be deleted.",
                )
              )
                return;
              void perform(async () => {
                await props.controller.discard();
                await navigate("/settings/recovery");
              });
            }}
          >
            Discard…
          </button>
        </div>
      )}
      {hostedMode() &&
        scope.canWrite &&
        (state.record || state.editAuthority === "required") &&
        state.command !== "committed" && (
          <section aria-label="Saved form edit authority">
            <p>
              {state.editAuthority === "held"
                ? "You can edit this saved form here."
                : "Editing is unavailable here. Another tab or device may be using this form. Your input is retained."}
            </p>
            {state.editAuthority !== "held" && (
              <button type="button" disabled={busy} onClick={() => void claim(false)}>
                Continue editing
              </button>
            )}
            {state.record?.status === "active" && (
              <button
                type="button"
                disabled={busy}
                onClick={() => {
                  setBusy(true);
                  void props.controller
                    .reviewSavedForm()
                    .catch(() => undefined)
                    .finally(() => setBusy(false));
                }}
              >
                Review saved changes
              </button>
            )}
            {state.editAuthority !== "held" && (
              <button
                type="button"
                disabled={busy}
                onClick={() => {
                  if (
                    window.confirm(
                      "Take over this saved form? The previous editor's next save will be rejected; their input will not be erased.",
                    )
                  )
                    void claim(true);
                }}
              >
                Take over editing
              </button>
            )}
            {state.error && <p role="alert">{state.error}</p>}
          </section>
        )}
      {actionError && <p role="alert">{actionError}</p>}
      <BlockedNavigation controller={props.controller} blocker={props.blocker} />
    </>
  );
}
