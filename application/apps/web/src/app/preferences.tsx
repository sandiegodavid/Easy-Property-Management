import { useLayoutEffect, useState, type ReactNode, createContext, useContext } from "react";
import { api } from "@epm/contracts";
import { Link } from "react-router-dom";
import type { components } from "@epm/contracts/generated";
import { useWorkspace } from "./workspace-gate";
import { defaultOrder, destination } from "./destinations";
import { mutation, MutationFailure } from "../shared/mutations";

type Preferences = components["schemas"]["PreferenceResponse"];
type Command = components["schemas"]["PreferenceInput"];
const defaults: Preferences = {
  appearance: "light",
  destinationOrder: defaultOrder,
  hiddenDestinationIds: [],
  revision: 0,
  updatedAt: null,
};
const PreferenceContext = createContext<ReturnType<typeof usePreferenceState> | null>(null);

function usePreferenceState() {
  const { bootstrap, scope } = useWorkspace();
  const [saved, setSaved] = useState(bootstrap.preferences);
  const [draft, setDraft] = useState(bootstrap.preferences ?? defaults);
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState("");
  const [conflict, setConflict] = useState(false);
  const [attempt, setAttempt] = useState<Command | null>(null);
  const writable =
    scope.canWrite &&
    bootstrap.preferencesState === "available" &&
    saved !== null &&
    bootstrap.capabilities.includes("operator.preferences");
  useLayoutEffect(() => {
    document.documentElement.dataset.theme = draft.appearance;
  }, [draft.appearance]);

  async function save() {
    if (!writable || pending || conflict) return;
    scope.requireWrite();
    const command = attempt ?? {
      appearance: draft.appearance,
      destinationOrder: draft.destinationOrder,
      hiddenDestinationIds: draft.hiddenDestinationIds,
      expectedRevision: saved.revision,
      idempotencyKey: crypto.randomUUID(),
    };
    setAttempt(command);
    setPending(true);
    setMessage("");
    try {
      const result = await mutation(() => api.PUT("/api/operator/preferences", { body: command }));
      scope.requireWrite();
      setSaved(result);
      setDraft(result);
      setAttempt(null);
      setMessage("Preferences saved.");
    } catch (error) {
      if (error instanceof MutationFailure && error.status === 409) {
        setConflict(true);
        setAttempt(null);
        setMessage(
          "Preferences changed in another window. Your choices are preserved. Load current preferences before applying them again.",
        );
      } else if (error instanceof MutationFailure && !error.outcomeUnknown) {
        setAttempt(null);
        setMessage(error.problem.message);
      } else {
        setMessage("Save outcome unknown. Retry the same request before making more changes.");
      }
    } finally {
      setPending(false);
    }
  }

  async function loadCurrent() {
    setPending(true);
    try {
      const result = await api.GET("/api/operator/preferences");
      if (!result.data) throw new Error("Unavailable");
      setSaved(result.data);
      setConflict(false);
      setMessage(
        "Current revision loaded. Your choices are preserved; review and save to apply them.",
      );
    } catch {
      setMessage("Current preferences could not be loaded. Your choices are preserved.");
    } finally {
      setPending(false);
    }
  }
  return { draft, setDraft, writable, pending, message, conflict, attempt, save, loadCurrent };
}

export function PreferencesProvider({ children }: { children: ReactNode }) {
  const value = usePreferenceState();
  return <PreferenceContext.Provider value={value}>{children}</PreferenceContext.Provider>;
}
export function usePreferences() {
  const value = useContext(PreferenceContext);
  if (!value) throw new Error("Preferences provider is required.");
  return value;
}

export function PreferenceSettings() {
  const { draft, setDraft, writable, pending, message, conflict, attempt, save, loadCurrent } =
    usePreferences();
  const editable = writable && !pending && !attempt;
  const middle = draft.destinationOrder.filter((id) => !destination(id)?.fixed);
  function move(index: number, delta: number) {
    const order = [...middle];
    const item = order.splice(index, 1)[0];
    if (!item) return;
    order.splice(index + delta, 0, item);
    setDraft({ ...draft, destinationOrder: ["home", ...order, "settings"] });
  }
  return (
    <>
      <h2>Appearance and navigation</h2>
      <p>
        <Link to="/settings/provider-categories">Provider categories</Link>
      </p>
      {!writable && (
        <p>Preference editing requires available preferences and workspace write access.</p>
      )}
      <fieldset disabled={!editable}>
        <legend>Appearance</legend>
        {(["light", "dark"] as const).map((appearance) => (
          <label key={appearance}>
            <input
              type="radio"
              name="appearance"
              checked={draft.appearance === appearance}
              onChange={() => setDraft({ ...draft, appearance })}
            />
            {appearance === "light" ? "Light" : "Dark"}
          </label>
        ))}
      </fieldset>
      <fieldset disabled={!editable}>
        <legend>Navigation</legend>
        <p>
          Home and Settings stay accessible. Hidden destinations remain in More and contextual
          links; hiding them does not hide obligations.
        </p>
        <ol>
          {middle.map((id, index) => (
            <li key={id}>
              <label>
                <input
                  type="checkbox"
                  checked={!draft.hiddenDestinationIds.includes(id)}
                  onChange={(event) =>
                    setDraft({
                      ...draft,
                      hiddenDestinationIds: event.target.checked
                        ? draft.hiddenDestinationIds.filter((item) => item !== id)
                        : [...draft.hiddenDestinationIds, id],
                    })
                  }
                />
                {destination(id)?.label}
              </label>
              <button
                aria-label={`Move ${destination(id)?.label} up`}
                disabled={index === 0}
                onClick={() => move(index, -1)}
              >
                Up
              </button>
              <button
                aria-label={`Move ${destination(id)?.label} down`}
                disabled={index === middle.length - 1}
                onClick={() => move(index, 1)}
              >
                Down
              </button>
            </li>
          ))}
        </ol>
        <button onClick={() => setDraft({ ...defaults, revision: draft.revision })}>
          Restore defaults
        </button>
      </fieldset>
      <button disabled={!writable || pending || conflict} onClick={() => void save()}>
        {pending ? "Saving…" : attempt ? "Retry save" : "Save preferences"}
      </button>
      {conflict && (
        <button disabled={pending} onClick={() => void loadCurrent()}>
          Load current preferences
        </button>
      )}
      {message && <p role="status">{message}</p>}
    </>
  );
}
