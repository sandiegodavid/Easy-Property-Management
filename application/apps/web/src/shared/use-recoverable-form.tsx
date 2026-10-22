import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { useForm, type DefaultValues, type FieldValues } from "react-hook-form";
import { useBlocker } from "react-router-dom";
import { useWorkspace } from "../app/workspace-gate";
import { RecoveryController, type FormIdentity, type Recovery } from "./recovery";

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
    return () => controller.dispose();
  }, [controller]);
  const navigationBlocked =
    !controller.isPristine && (state.draft !== "saved" || state.command === "submitting");
  const blocker = useBlocker(navigationBlocked);
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

export function RecoveryNavigation({
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
