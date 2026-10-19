import { useEffect, useId, useRef, useState } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import { api } from "@epm/contracts";
import { record, scalar } from "@epm/contracts/workflows";
import { useWorkspace } from "../app/workspace-gate";
import { DisclosureHelp } from "../shared/home-disclosure-help";
import { type Choice, type Choices } from "./fields";
import { readResult } from "./reads";
import { OwnerContactFields } from "./owner-contact-fields";
import { SourceWorkflowLink as Link } from "../shared/home-navigation";
import { useLocation } from "react-router-dom";
import { ownershipShareProblem } from "../shared/ownership-shares";

export function OwnershipFields({
  timeZone,
  value,
  onChange,
  choices,
  disabled,
  onAddingChange,
  mode = "change",
}: {
  timeZone?: string;
  value: Record<string, unknown>;
  onChange: (next: Record<string, unknown>) => void;
  choices: Choices;
  disabled: boolean;
  onAddingChange: (pending: boolean) => void;
  mode?: "change" | "create";
}) {
  const { scope } = useWorkspace();
  const location = useLocation();
  const id = useId();
  const [adding, setAdding] = useState(false);
  const [creating, setCreating] = useState(false);
  const [input, setInput] = useState("");
  const [search, setSearch] = useState<string>();
  const searchTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => clearTimeout(searchTimer.current), []);
  const [cursors, setCursors] = useState<(string | undefined)[]>([undefined]);
  const cursor = cursors[cursors.length - 1];
  const resultsRef = useRef<HTMLDivElement>(null);
  const [name, setName] = useState("");
  const [kind, setKind] = useState("individual");
  const [contacts, setContacts] = useState<Record<string, unknown>[]>([]);
  const [selectedChoices, setSelectedChoices] = useState<Choice[]>([]);
  const searchPending = input.trim() !== (search ?? "");
  const showingResults = !!input.trim() || search !== undefined;
  const searchByName = (next: string) => {
    clearTimeout(searchTimer.current);
    setInput(next);
    setCursors([undefined]);
    if (!next.trim()) setSearch(undefined);
    else searchTimer.current = setTimeout(() => setSearch(next.trim()), 300);
  };
  const owners = Array.isArray(value.ownerships) ? value.ownerships.map(record) : [];
  const known = [...(choices.partyId ?? []), ...selectedChoices];
  const unknownIds = [
    ...new Set(owners.flatMap((owner) => (owner.partyId ? [scalar(owner.partyId)] : []))),
  ];
  const recoveredNames = useQueries({
    queries: unknownIds.map((partyId) => ({
      queryKey: scope.key("ownership-owner", partyId),
      queryFn: async ({ signal }: { signal: AbortSignal }) =>
        readResult(
          await api.GET("/api/parties/{party_id}", {
            signal,
            params: { path: { party_id: partyId } },
          }),
        ),
    })),
  });
  const parties = useQuery({
    queryKey: scope.key("ownership-owner-search", search, cursor),
    enabled: adding && !creating && search !== undefined && !searchPending,
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/parties/selection", {
          signal,
          params: { query: { search: search || undefined, cursor, limit: 10 } },
        }),
      ),
  });
  const matches = searchPending ? undefined : parties.data;
  const searching = searchPending || parties.isFetching;
  const add = (owner: Record<string, unknown>, choice?: Choice) => {
    clearTimeout(searchTimer.current);
    if (choice)
      setSelectedChoices((current) => [...current.filter((item) => item.id !== choice.id), choice]);
    onChange({ ...value, ownerships: [...owners, owner] });
    setAdding(false);
    onAddingChange(false);
    setCreating(false);
    setInput("");
    setSearch(undefined);
    setCursors([undefined]);
    setName("");
    setContacts([]);
  };
  const changeOwner = (index: number, next: Record<string, unknown>) =>
    onChange({
      ...value,
      ownerships: owners.map((owner, position) => (position === index ? next : owner)),
    });
  return (
    <>
      {mode === "change" && (
        <div className="ownership-effective-date">
          <div className="ownership-date-heading">
            <label htmlFor={`${id}-date`}>Effective date</label>
            <DisclosureHelp
              label="How the ownership effective date works"
              text={`Ownership changes take effect on this calendar date in ${timeZone ?? "the property’s time zone"}, not your browser’s time zone. The previous owners’ relationships end on this date and the selected owners’ relationships begin on it. A future date schedules the change.`}
            />
          </div>
          <input
            id={`${id}-date`}
            type="date"
            required
            disabled={disabled}
            value={scalar(value.effectiveOn, "")}
            onChange={(event) => onChange({ ...value, effectiveOn: event.target.value })}
          />
        </div>
      )}
      <fieldset className="ownership-owners">
        <legend>{mode === "change" ? "Owners from this date" : "Owners"}</legend>
        <p className="property-edit-hint">
          {mode === "create"
            ? "Keep You if you own this property. Add other owners for a managed or co-owned property, then remove You if needed."
            : "Keep everyone who will own the property from this date. Remove owners who are leaving and add anyone joining. Previous owners and shares stay in history."}
        </p>
        <details className="ownership-share-help">
          <summary>How ownership percentages work</summary>
          <p className="property-edit-hint">
            Enter each owner's percentage if known, or leave it blank as Not recorded. Known shares
            cannot exceed 100%; when all shares are recorded they must total 100%. Shares do not
            calculate payments or distributions.
          </p>
        </details>
        {ownershipShareProblem(owners) && <p role="alert">{ownershipShareProblem(owners)}</p>}
        <ul className="ownership-selected">
          {owners.map((owner, index) => {
            const lookup = recoveredNames.find((result) => result.data?.id === owner.partyId);
            const ownerName =
              owner.ownerKind === "local_operator"
                ? "You"
                : owner.inlineParty
                  ? scalar(record(owner.inlineParty).displayName, "New owner")
                  : (known.find((item) => item.id === owner.partyId)?.label ??
                    lookup?.data?.displayName ??
                    "Loading owner…");
            return (
              <li key={index}>
                <header className="ownership-owner-heading">
                  <div className="ownership-selected-name">
                    <strong>{ownerName}</strong>
                    {owner.inlineParty !== undefined && (
                      <span>New owner · created when you save</span>
                    )}
                  </div>
                  {
                    <button
                      type="button"
                      disabled={disabled || owners.length === 1}
                      aria-label={`Remove ${ownerName}`}
                      onClick={() =>
                        onChange({
                          ...value,
                          ownerships: owners.filter((_, position) => position !== index),
                        })
                      }
                    >
                      Remove
                    </button>
                  }
                </header>
                {
                  <div className="workflow-field">
                    <label htmlFor={`${id}-share-${index}`}>
                      Ownership share for {ownerName} (%)
                    </label>
                    <input
                      id={`${id}-share-${index}`}
                      type="number"
                      min="0.01"
                      max="100"
                      step="0.01"
                      inputMode="decimal"
                      placeholder="Not recorded"
                      disabled={disabled}
                      value={scalar(owner.sharePercent, "")}
                      onChange={(event) =>
                        changeOwner(index, { ...owner, sharePercent: event.target.value || null })
                      }
                    />
                  </div>
                }
                {!!owner.partyId && (
                  <div className="owner-contact-details">
                    {lookup?.data ? (
                      <>
                        <dl>
                          {lookup.data.contactMethods
                            ?.filter((method) => method.status === "active")
                            .map((method) => (
                              <div key={method.id}>
                                <dt>
                                  {method.label ||
                                    (method.methodKind === "mailing_address"
                                      ? "Mailing address"
                                      : method.methodKind === "email"
                                        ? "Email"
                                        : "Phone")}
                                </dt>
                                <dd>
                                  {method.displayValue}
                                  {method.extension && ` ext. ${method.extension}`}
                                </dd>
                              </div>
                            ))}
                        </dl>
                        {!lookup.data.contactMethods?.some(
                          (method) => method.status === "active",
                        ) && <p>No contact details recorded.</p>}
                        {
                          <Link
                            to={`/parties?identity=${scalar(owner.partyId)}`}
                            state={{ returnTo: location.pathname + location.search }}
                          >
                            Manage contact details
                          </Link>
                        }
                      </>
                    ) : (
                      <p role="status">Loading contact details…</p>
                    )}
                  </div>
                )}
                {owner.inlineParty !== undefined && (
                  <div className="ownership-new-fields">
                    <label>
                      New owner name
                      <input
                        required
                        maxLength={240}
                        disabled={disabled}
                        value={scalar(record(owner.inlineParty).displayName, "")}
                        onChange={(event) =>
                          changeOwner(index, {
                            ...owner,
                            inlineParty: {
                              ...record(owner.inlineParty),
                              displayName: event.target.value,
                            },
                          })
                        }
                      />
                    </label>
                    <label>
                      Person or organization
                      <select
                        disabled={disabled}
                        value={scalar(record(owner.inlineParty).partyKind, "individual")}
                        onChange={(event) =>
                          changeOwner(index, {
                            ...owner,
                            inlineParty: {
                              ...record(owner.inlineParty),
                              partyKind: event.target.value,
                            },
                          })
                        }
                      >
                        <option value="individual">Person</option>
                        <option value="organization">Organization</option>
                      </select>
                    </label>
                  </div>
                )}
                {owner.inlineParty !== undefined && (
                  <OwnerContactFields
                    value={record(owner.inlineParty).contacts}
                    disabled={disabled}
                    onChange={(next) =>
                      changeOwner(index, {
                        ...owner,
                        inlineParty: { ...record(owner.inlineParty), contacts: next },
                      })
                    }
                  />
                )}
              </li>
            );
          })}
        </ul>
        {recoveredNames.some((result) => result.error) && (
          <p role="alert">
            Some owner contact details could not be loaded. Reopen the form to try again.
          </p>
        )}
        {!adding ? (
          <button
            type="button"
            disabled={disabled || owners.length >= 100}
            onClick={() => {
              setAdding(true);
              onAddingChange(true);
            }}
          >
            Add owner
          </button>
        ) : (
          <section className="ownership-add" aria-label="Add an owner">
            <div className="ownership-add-heading">
              <h3>Add an owner</h3>
              <button
                type="button"
                disabled={disabled}
                onClick={() => {
                  clearTimeout(searchTimer.current);
                  setAdding(false);
                  onAddingChange(false);
                  setCreating(false);
                  setSearch(undefined);
                  setCursors([undefined]);
                  setInput("");
                  setName("");
                  setContacts([]);
                }}
              >
                Cancel
              </button>
            </div>
            <p className="property-edit-hint">
              Reuse a saved person or organization, or create a new owner. They will be saved with
              the property’s ownership, not as a separate step.
            </p>
            <div className="ownership-add-options" aria-label="Choose how to add an owner">
              <button
                type="button"
                disabled={disabled}
                aria-pressed={!creating}
                onClick={() => {
                  if (creating) {
                    setCreating(false);
                    searchByName(input);
                  }
                }}
              >
                Find an existing owner
              </button>
              <button
                type="button"
                disabled={disabled}
                aria-pressed={creating}
                onClick={() => {
                  if (!creating) {
                    clearTimeout(searchTimer.current);
                    setName((current) => current || input.trim());
                    setCreating(true);
                  }
                }}
              >
                Create a new owner
              </button>
            </div>
            {!creating ? (
              <>
                {!owners.some((owner) => owner.ownerKind === "local_operator") && (
                  <button
                    type="button"
                    disabled={disabled}
                    onClick={() => add({ ownerKind: "local_operator" })}
                  >
                    Add yourself
                  </button>
                )}
                <div className="ownership-search">
                  <label>
                    Find an owner by name
                    <input
                      type="search"
                      value={input}
                      placeholder="Search people or organizations"
                      maxLength={200}
                      disabled={disabled}
                      onChange={(event) => searchByName(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") {
                          event.preventDefault();
                        }
                      }}
                    />
                  </label>
                  <button
                    type="button"
                    disabled={disabled}
                    onClick={() => {
                      clearTimeout(searchTimer.current);
                      setInput("");
                      setSearch("");
                      setCursors([undefined]);
                    }}
                  >
                    Browse owners
                  </button>
                </div>
                {!showingResults && (
                  <p className="property-edit-hint">
                    Start typing to find a saved owner, or browse 10 at a time.
                  </p>
                )}
                {showingResults && (
                  <div
                    className="ownership-results-viewport"
                    ref={resultsRef}
                    role="region"
                    aria-label="Matching owners"
                    aria-busy={searching}
                  >
                    {searching && <p role="status">Searching owners…</p>}
                    {!searchPending && parties.error && <p role="alert">{parties.error.message}</p>}
                    {matches && (
                      <>
                        <ul className="ownership-search-results">
                          {matches.items.map((party) => {
                            const selected = owners.some((owner) => owner.partyId === party.id);
                            return (
                              <li key={party.id}>
                                <div>
                                  <strong>{party.displayName}</strong>
                                  <span>
                                    {party.partyKind === "organization" ? "Organization" : "Person"}
                                  </span>
                                </div>
                                <button
                                  type="button"
                                  disabled={disabled || selected || searching}
                                  aria-label={
                                    selected
                                      ? `${party.displayName} already added`
                                      : `Add ${party.displayName}`
                                  }
                                  onClick={() =>
                                    add(
                                      { ownerKind: "client_owner", partyId: party.id },
                                      { id: party.id, label: party.displayName },
                                    )
                                  }
                                >
                                  {selected ? "Added" : "Add"}
                                </button>
                              </li>
                            );
                          })}
                        </ul>
                        {!matches.items.length && (
                          <p>No matching names. Try another name or choose Create a new owner.</p>
                        )}
                      </>
                    )}
                  </div>
                )}
                {showingResults && (
                  <nav aria-label="Owner search pages" className="ownership-pagination">
                    <button
                      type="button"
                      disabled={disabled || cursors.length === 1 || searching}
                      onClick={() => {
                        if (resultsRef.current) resultsRef.current.scrollTop = 0;
                        setCursors((current) => current.slice(0, -1));
                      }}
                    >
                      Previous
                    </button>
                    <span aria-live="polite">
                      {searching
                        ? "Loading…"
                        : matches?.items.length
                          ? `${(cursors.length - 1) * 10 + 1}–${(cursors.length - 1) * 10 + matches.items.length}`
                          : parties.error
                            ? "Unavailable"
                            : "0 results"}
                    </span>
                    <button
                      type="button"
                      disabled={disabled || !matches?.nextCursor || searching}
                      onClick={() => {
                        const next = matches?.nextCursor;
                        if (next) {
                          if (resultsRef.current) resultsRef.current.scrollTop = 0;
                          setCursors((current) => [...current, next]);
                        }
                      }}
                    >
                      Next
                    </button>
                  </nav>
                )}
              </>
            ) : (
              <>
                <p className="property-edit-hint">
                  Enter their name below. Contact details are optional. Nothing is saved until you
                  save the property form.
                </p>
                <div className="ownership-new-fields">
                  <label>
                    New owner name
                    <input
                      maxLength={240}
                      disabled={disabled}
                      value={name}
                      onChange={(event) => setName(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") event.preventDefault();
                      }}
                    />
                  </label>
                  <label>
                    Person or organization
                    <select
                      disabled={disabled}
                      value={kind}
                      onChange={(event) => setKind(event.target.value)}
                    >
                      <option value="individual">Person</option>
                      <option value="organization">Organization</option>
                    </select>
                  </label>
                </div>
                <OwnerContactFields value={contacts} onChange={setContacts} disabled={disabled} />
                <div className="ownership-add-actions">
                  <button
                    type="button"
                    disabled={
                      disabled ||
                      !name.trim() ||
                      contacts.some((contact) => !scalar(contact.value).trim())
                    }
                    onClick={() =>
                      add({
                        ownerKind: "client_owner",
                        inlineParty: { partyKind: kind, displayName: name.trim(), contacts },
                      })
                    }
                  >
                    Add to owners
                  </button>
                </div>
              </>
            )}
          </section>
        )}
      </fieldset>
    </>
  );
}
