import { StrictMode, useState, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import {
  useRead,
  words,
  time,
  lifecycle,
  type Read,
  type Observation,
  type Directory,
  type Operator,
  type Access,
  type Runtime,
  type Recovery,
  type Capacity,
  type Qualification,
  type Operation,
  type OperationList,
} from "./reads";
import "./style.css";
import { SetupPage } from "./setup";
import { Lifecycle } from "./lifecycle";
import { UpgradePage } from "./upgrades";
import { BatchPage, useUpgradeSelection } from "./upgrade-batches";

function ReadState({ read }: { read: Read<unknown> }) {
  if (read.expired)
    return (
      <p role="alert">
        Your private session ended. <a href={window.location.pathname}>Sign in again</a>. Admitted
        operations have not been resubmitted.
      </p>
    );
  if (read.failed)
    return <p role="status">Connection unavailable. Retained information may be stale.</p>;
  if (!read.data) return <p role="status">Loading…</p>;
  return null;
}
function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="panel" aria-label={title}>
      <h2>{title}</h2>
      {children}
    </section>
  );
}
function Observed<T>({
  read,
  children,
}: {
  read: Read<Observation<T>>;
  children: (data: T) => ReactNode;
}) {
  const value = read.data;
  return (
    <>
      <ReadState read={read} />
      <p className="state">
        {read.failed && value?.data ? "Stale" : words(value?.state ?? "unknown")}
        {value?.refreshing ? " · Checking…" : ""}
      </p>
      {value?.data ? (
        children(value.data)
      ) : (
        <p>No verified reading. Check the private collector or source service.</p>
      )}
      <p className="stamp">Last verified: {time(value?.observed)}</p>
      {value?.state !== "available" && value?.attempted != null && (
        <p className="stamp">Last check attempted: {time(value.attempted)}</p>
      )}
    </>
  );
}
function QualificationPlans() {
  const read = useRead<Qualification>("/admin-api/qualification");
  return (
    <>
      <ReadState read={read} />
      <p>
        Recorded ordinary ceiling: <strong>{read.data?.capacity?.ceiling ?? "Unknown"}</strong>.
        Current host applicability requires matching fresh capacity evidence.
      </p>
      <p>
        Additional operators remain unqualified until the private three-test procedure and explicit
        promotion succeed. A/B registration is not new acceptance.
      </p>
      <p>
        Use the installed private launcher: <code>epm-admin operations</code>. Follow the installed
        HOSTED_ADMIN_OPERATIONS runbook; never edit the database.
      </p>
      {read.data?.plans.map((plan) => (
        <article className="item" key={plan.id}>
          <h3>{words(plan.state)} qualification</h3>
          <p>Plan reference: {plan.id}</p>
          <p>Created {time(plan.created)}</p>
          <ul>
            {read.data?.evidence
              .filter((e) => e.qualification_id === plan.id)
              .map((e, index) => (
                <li key={`${e.kind}-${index}`}>
                  {words(e.kind)}: {e.passed ? "Passed" : "Failed"} · Observed {time(e.observed)} ·
                  Valid until {time(e.expires)}
                </li>
              ))}
          </ul>
        </article>
      ))}
      {read.data && !read.data.plans.length && <p>No qualification plan registered.</p>}
      <p>
        Showing up to 20 recent plans and {read.data?.evidence_limit ?? 200} evidence records.
        Private tooling retains the complete history.
      </p>
    </>
  );
}
function HostSummary({ directory }: { directory: Directory | undefined }) {
  const capacity = useRead<Observation<Capacity>>("/admin-api/observations/capacity", 5000);
  const tunnel = useRead<Observation<{ service: string; startup: string }>>(
    "/admin-api/observations/tunnel",
    5000,
  );
  return (
    <div className="grid">
      <Panel title="Host capacity">
        <Observed read={capacity}>
          {(c) => (
            <dl>
              <dt>Uncommitted memory</dt>
              <dd>
                {Math.round((c.memory_total - c.memory_committed) / 1048576)} MiB (reserved
                capacity; not measured free RAM)
              </dd>
              <dt>Free disk</dt>
              <dd>{Math.round(c.disk_free / 1048576)} MiB</dd>
              <dt>Reserved disk</dt>
              <dd>{Math.round(c.disk_committed / 1048576)} MiB</dd>
              <dt>Observed release / profile</dt>
              <dd>
                {c.release} / {c.profile}
              </dd>
              <dt>Inventory clear</dt>
              <dd>{c.inventory_clear ? "Yes" : "Needs reconciliation"}</dd>
              <dt>Observed active instances</dt>
              <dd>{c.active_count} (not an acceptance or online-presence claim)</dd>
              <dt>Measured available memory</dt>
              <dd>
                Unknown — the current capacity report records commitments, not a live free-memory
                reading.
              </dd>
            </dl>
          )}
        </Observed>
        <p>Remaining Access seats: Unknown. Verify the provider account before invitations.</p>
      </Panel>
      <Panel title="Public tunnel">
        <Observed read={tunnel}>
          {(t) => (
            <>
              <p>{words(t.service)}</p>
              <p>Automatic startup: {words(t.startup)}</p>
            </>
          )}
        </Observed>
        <p>Running now does not prove reboot recovery or public Access enforcement.</p>
      </Panel>
      <Panel title="Recovery availability">
        {!directory && <p>Recovery observations are unavailable.</p>}
        {directory?.items.map((item) => (
          <p key={item.key}>
            <strong>{item.name}</strong>: {recoveryState(item.recovery)} · Last verified off-host
            read-back: {time(item.recovery.data?.off_host_readback)}
          </p>
        ))}
        <p>
          Showing this directory page only. Open an operator for its private recovery checklist.
        </p>
        <p>
          Recovery age warns after 20 hours and is overdue after 24 hours; it does not automatically
          disable existing operators.
        </p>
      </Panel>
    </div>
  );
}
function recoveryState(recovery: Observation<Recovery>) {
  return words(
    recovery.state === "available" ? (recovery.data?.policy_state ?? "unknown") : recovery.state,
  );
}
function DirectoryPage() {
  const { selected, save } = useUpgradeSelection();
  const [offset, setOffset] = useState(0),
    [filter, setFilter] = useState("all");
  const read = useRead<Directory>(`/admin-api/operators/page/${offset}`);
  const items = read.data?.items.filter((item) => {
    const status = lifecycle(item.access.state === "available" ? item.access.data : null);
    if (filter === "recovery") return recoveryState(item.recovery) !== "Verified";
    return (
      filter === "all" ||
      (filter === "enabled" ? status === "Access enabled" : status !== "Access enabled")
    );
  });
  const pageExceedsSelection =
    selected.length +
      (items?.filter((item) => !selected.some((other) => other.key === item.key)).length ?? 0) >
    50;
  return (
    <>
      <div className="heading">
        <h1>Operators</h1>
        <a className="button" href="/setups/new" aria-describedby="creation-gate">
          Add operator
        </a>
      </div>
      <p id="creation-gate">
        Save an operator setup while capacity is unresolved. Creating an instance requires fresh
        qualification, resource and Access-seat checks.
      </p>
      <HostSummary directory={read.failed || read.expired ? undefined : read.data} />
      <Panel title="Qualification">
        <QualificationPlans />
      </Panel>
      <Panel title="Operator directory">
        <p>{selected.length} selected · Maximum 50 operators per batch</p>
        <a href="/upgrade-batches">View upgrade batches</a>
        {pageExceedsSelection && (
          <p>
            Select individual operators from this page to stay within the 50-operator batch limit.
          </p>
        )}
        <div className="actions">
          <button
            disabled={!items?.length || read.failed || read.expired || pageExceedsSelection}
            onClick={() =>
              save(
                [
                  ...selected,
                  ...(items ?? [])
                    .filter((item) => Number.isInteger(item.registered_revision))
                    .map((item) => ({
                      key: item.key,
                      name: item.name,
                      revision: item.registered_revision,
                      release: item.release,
                      access:
                        item.access.state === "available" ? lifecycle(item.access.data) : "Unknown",
                    })),
                ].sort((a, b) => a.name.localeCompare(b.name) || a.key.localeCompare(b.key)),
              )
            }
          >
            Select this page
          </button>
          <button disabled={!selected.length} onClick={() => save([])}>
            Clear selection
          </button>
          {selected.length ? (
            <a className="button" href="/upgrade-batches/new">
              Upgrade selected operators
            </a>
          ) : (
            <button disabled>Upgrade selected operators</button>
          )}
        </div>
        <ReadState read={read} />
        <label htmlFor="operator-filter">Show operators on this page</label>
        <select id="operator-filter" value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option value="all">All</option>
          <option value="enabled">Access enabled</option>
          <option value="review">Needs review or unknown</option>
          <option value="recovery">Recovery needs attention</option>
        </select>
        <p>
          Access counts are unknown until current source observations are available. Registration
          alone does not mean active or accepted.
        </p>
        {read.data && (
          <p>
            {read.data.total} registered operators ·{" "}
            {read.data.offset + (read.data.items.length ? 1 : 0)}–
            {read.data.offset + read.data.items.length} shown.
          </p>
        )}
        <div className="operator-table" role="list">
          {items?.map((item) => (
            <article role="listitem" className="item" key={item.key}>
              <label htmlFor={`upgrade-select-${item.key}`}>
                <input
                  id={`upgrade-select-${item.key}`}
                  type="checkbox"
                  checked={selected.some((other) => other.key === item.key)}
                  disabled={
                    read.failed ||
                    !Number.isInteger(item.registered_revision) ||
                    (selected.length >= 50 && !selected.some((other) => other.key === item.key))
                  }
                  onChange={(event) =>
                    save(
                      event.target.checked
                        ? [
                            ...selected,
                            {
                              key: item.key,
                              name: item.name,
                              revision: item.registered_revision,
                              release: item.release,
                              access:
                                item.access.state === "available"
                                  ? lifecycle(item.access.data)
                                  : "Unknown",
                            },
                          ].sort(
                            (a, b) => a.name.localeCompare(b.name) || a.key.localeCompare(b.key),
                          )
                        : selected.filter((other) => other.key !== item.key),
                    )
                  }
                />
                Select {item.name}
              </label>
              <h3>
                <a href={`/operators/${item.key}`}>{item.name}</a>
              </h3>
              <p>{item.email}</p>
              <dl>
                <dt>Access / setup</dt>
                <dd>
                  {item.access.state === "available"
                    ? lifecycle(item.access.data)
                    : words(item.access.state)}
                </dd>
                <dt>Expires</dt>
                <dd>{time(item.access.data?.expires)}</dd>
                <dt>Service</dt>
                <dd>
                  {item.runtime.state === "available" && item.runtime.data
                    ? words(item.runtime.data.service)
                    : words(item.runtime.state)}
                </dd>
                <dt>Recovery</dt>
                <dd>{recoveryState(item.recovery)}</dd>
              </dl>
            </article>
          ))}
        </div>
        {items?.length === 0 && <p>No operators match this page filter.</p>}
        <nav aria-label="Operator pages">
          <button disabled={offset === 0} onClick={() => setOffset(offset - 50)}>
            Previous 50
          </button>
          <button
            disabled={read.data?.next == null}
            onClick={() => setOffset(read.data?.next ?? 0)}
          >
            Next 50
          </button>
        </nav>
      </Panel>
    </>
  );
}
function OperatorDetails({ instance }: { instance: string }) {
  // A detail selects one registered key; no cross-operator business queries.
  const record = useRead<{ items: Operator[] }>(`/admin-api/operators/${instance}`);
  const access = useRead<Observation<Access>>(
    `/admin-api/operators/${instance}/observations/access`,
    5000,
  );
  const runtime = useRead<Observation<Runtime>>(
    `/admin-api/operators/${instance}/observations/runtime`,
    5000,
  );
  const recovery = useRead<Observation<Recovery>>(
    `/admin-api/operators/${instance}/observations/recovery`,
    5000,
  );
  const operations = useRead<OperationList>("/admin-api/operations");
  const upgrade = operations.data?.items.find(
    (op) =>
      op.target === instance &&
      op.kind.startsWith("upgrade") &&
      !["succeeded", "cancelled"].includes(op.state),
  );
  const item = record.data?.items[0];
  return (
    <>
      <a className="back" href="/operators">
        ← Back to Operators
      </a>
      <h1>{item?.name ?? "Operator details"}</h1>
      <ReadState read={record} />
      {item && (
        <p>
          {item.email} ·{" "}
          <a href={`https://${item.hostname}`} target="_blank" rel="noreferrer">
            {item.hostname}
          </a>
        </p>
      )}
      {item?.setup_id ? (
        <p>
          <a className="button" href={`/setups/${item.setup_id}`}>
            Resume operator setup
          </a>
        </p>
      ) : (
        <p className="notice">
          Existing allocation. Recovery verification and explicit access changes are available
          below; registration alone is not onboarding acceptance.
        </p>
      )}
      {item && (
        <Lifecycle
          instance={instance}
          hostname={item.hostname}
          email={item.email}
          expires={access.data?.data?.expires}
          upgrading={operations.data?.items.some(
            (op) =>
              op.target === instance &&
              op.kind.startsWith("upgrade") &&
              !["succeeded", "cancelled"].includes(op.state),
          )}
        />
      )}
      <div className="grid">
        <Panel title="Access">
          <Observed read={access}>
            {(a) => (
              <dl>
                <dt>Current access</dt>
                <dd>{lifecycle(a)}</dd>
                <dt>Starts</dt>
                <dd>{time(a.starts)}</dd>
                <dt>Expires</dt>
                <dd>{time(a.expires)}</dd>
                <dt>Binding matches configuration</dt>
                <dd>{a.binding_matches ? "Yes" : "No — reconcile privately"}</dd>
                <dt>Pending verified enrollments</dt>
                <dd>{a.pending_enrollments}</dd>
                <dt>Capability profile</dt>
                <dd>
                  Records:{" "}
                  {a.capabilities.includes("records.write") ? "Read and write" : "Read only"}.
                  Files:{" "}
                  {a.capabilities.includes("files.write")
                    ? "Read and write"
                    : a.capabilities.includes("files.read")
                      ? "Read only"
                      : "Unavailable"}
                  .
                </dd>
              </dl>
            )}
          </Observed>
          <p>Valid app-session count: Unknown. No online-presence claim.</p>
        </Panel>
        <Panel title="Runtime and capacity">
          <p>
            <a
              href={
                upgrade
                  ? `/operators/${instance}/upgrade/${upgrade.id}`
                  : `/operators/${instance}/upgrade`
              }
            >
              {upgrade ? "View upgrade progress" : "Upgrade release"}
            </a>
          </p>
          <p>Registered release: {item?.release ?? "Unknown"}</p>
          <p>Registered profile: {item?.profile ?? "Unknown"}</p>
          <Observed read={runtime}>
            {(r) => (
              <dl>
                <dt>Service</dt>
                <dd>{words(r.service)}</dd>
                <dt>Exact mount</dt>
                <dd>{r.mount_verified ? "Verified" : "Needs review"}</dd>
                <dt>Registered runtime</dt>
                <dd>{r.release_matches ? "Matches" : "Discrepancy — reconcile privately"}</dd>
              </dl>
            )}
          </Observed>
          <p>New acceptance / rollback evidence: Not established by registration.</p>
        </Panel>
        <Panel title="Recovery">
          <Observed read={recovery}>
            {(r) => (
              <dl>
                <dt>Local archive</dt>
                <dd>{time(r.local_archive)}</dd>
                <dt>Off-host read-back</dt>
                <dd>{time(r.off_host_readback)}</dd>
                <dt>Restore drill</dt>
                <dd>{time(r.restore_drill)}</dd>
                <dt>Approved binding verification</dt>
                <dd>{time(r.approved_binding)}</dd>
                <dt>Recovery follow-up</dt>
                <dd>
                  {words(r.policy_state ?? "unknown")} ·{" "}
                  {r.acknowledged ? "Acknowledged" : "Not acknowledged"}
                </dd>
                <dt>Last attempt</dt>
                <dd>{time(r.attempted)}</dd>
              </dl>
            )}
          </Observed>
          <p>Use the private recovery runbook; an archive on disk alone is insufficient.</p>
        </Panel>
      </div>
      <Panel title="Recent operations">
        <ReadState read={operations} />
        <OperationRows items={operations.data?.items.filter((op) => op.target === instance)} />
        <p>
          Up to 50 recent administrator operations are searched. Use the original operation
          reference for older work.
        </p>
      </Panel>
    </>
  );
}
function OperationRows({ items }: { items?: OperationList["items"] }) {
  return (
    <>
      {items?.map((op) => (
        <article className="item" key={op.id}>
          <h3>
            <a href={`/operations/${op.id}`}>
              {words(op.kind)} · {op.target}
            </a>
          </h3>
          <span className="state">{words(op.state)}</span>
          <p>Updated {time(op.updated)}</p>
        </article>
      ))}
      {items?.length === 0 && <p>No recent operations.</p>}
    </>
  );
}
function Operations() {
  const read = useRead<OperationList>("/admin-api/operations");
  return (
    <>
      <h1>Recent operations</h1>
      <ReadState read={read} />
      <OperationRows items={read.data?.items} />
      <p>
        Up to 50 recent operations. Refreshing or reconnecting only checks status; it does not
        repeat a command.
      </p>
    </>
  );
}
function OperationDetails({ id }: { id: string }) {
  const read = useRead<Operation>(`/admin-api/operation-details/${id}`, 2000);
  return (
    <>
      <a className="back" href="/operations">
        ← Back to Operations
      </a>
      <h1>Operation progress</h1>
      <ReadState read={read} />
      {read.data && (
        <>
          <Panel title="Operation">
            <p className="state">{words(read.data.state)}</p>
            <dl>
              <dt>Safe correlation reference</dt>
              <dd>{read.data.id}</dd>
              <dt>Target</dt>
              <dd>
                <a href={`/operators/${read.data.target}`}>{read.data.target}</a>
              </dd>
              <dt>Administrator</dt>
              <dd>{read.data.actor}</dd>
              <dt>Reason</dt>
              <dd>{read.data.reason}</dd>
              <dt>Created</dt>
              <dd>{time(read.data.created)}</dd>
              <dt>Last checkpoint</dt>
              <dd>{time(read.data.updated)}</dd>
            </dl>
            {read.data.error && (
              <p className="notice">
                This operation needs private review. Inspect the original operation with the
                installed launcher; do not submit another job.
              </p>
            )}
            {read.data.kind === "source" && read.data.state === "waiting" && (
              <div className="notice">
                <p>
                  App access is fenced. Disable is awaiting independently verified manual Cloudflare
                  denial. Keep the Access application protected; privately replace its allowance
                  with Block everyone, then run:
                </p>
                <pre>{`sudo /opt/epm/admin/venv/bin/python -I /opt/epm/admin/admin_console.py verify-edge-denial --operation ${read.data.id}`}</pre>
                <p>
                  Resume this original operation after verification; do not submit another disable.
                </p>
              </div>
            )}
            <p>
              This page is read-only. Safe stop retains resources; resuming requires private
              revision/authority review.
            </p>
          </Panel>
          <Panel title="Checked steps">
            <ol>
              {read.data.steps.map((step) => (
                <li key={step.sequence}>
                  {words(step.kind)} — {words(step.state)} · {time(step.checked)}
                </li>
              ))}
            </ol>
          </Panel>
          <Panel title="Operation history">
            <ol>
              {read.data.events.map((event, i) => (
                <li key={i}>
                  {words(event.action)} · {time(event.recorded)}
                </li>
              ))}
            </ol>
          </Panel>
        </>
      )}
    </>
  );
}
function Discrepancies() {
  const read = useRead<Observation<{ unregistered: string[]; missing: string[] }>>(
    "/admin-api/observations/discrepancies",
    5000,
  );
  return (
    <>
      <h1>Inventory discrepancies</h1>
      <Panel title="Registered versus discovered keys">
        <Observed read={read}>
          {(d) => (
            <>
              <h3>Unregistered resources</h3>
              <ul>
                {d.unregistered.map((key) => (
                  <li key={key}>
                    {key} — inspect privately before adoption; conflicting allocation is blocked.
                  </li>
                ))}
              </ul>
              <h3>Registered but not discovered</h3>
              <ul>
                {d.missing.map((key) => (
                  <li key={key}>
                    {key} — inspect the service and configuration using the private reconciliation
                    runbook.
                  </li>
                ))}
              </ul>
              {!d.missing.length && !d.unregistered.length && (
                <p>
                  No key discrepancies observed. This does not prove configuration, release,
                  provider or recovery acceptance.
                </p>
              )}
            </>
          )}
        </Observed>
        <p>
          Unknown resources are never automatically adopted or deleted. Detail runtime checks
          compare the exact registered configuration.
        </p>
      </Panel>
    </>
  );
}
function App() {
  const path = window.location.pathname.split("/");
  const [dark, setDark] = useState(window.matchMedia("(prefers-color-scheme: dark)").matches);
  const content =
    path[1] === "upgrade-batches" ? (
      <BatchPage id={path[2]} />
    ) : path[1] === "setups" ? (
      <SetupPage id={path[2]} />
    ) : path[1] === "qualification" ? (
      <>
        <h1>Qualification plan</h1>
        <Panel title="Private qualification">
          <QualificationPlans />
        </Panel>
      </>
    ) : path[1] === "discrepancies" ? (
      <Discrepancies />
    ) : path[1] === "operations" ? (
      path[2] ? (
        <OperationDetails id={path[2]} />
      ) : (
        <Operations />
      )
    ) : path[1] === "operators" && path[2] ? (
      path[3] === "upgrade" ? (
        <UpgradePage instance={path[2]} id={path[4]} />
      ) : (
        <OperatorDetails instance={path[2]} />
      )
    ) : (
      <DirectoryPage />
    );
  return (
    <div data-appearance={dark ? "dark" : "light"}>
      <nav aria-label="Administration">
        <a
          href="/operators"
          aria-current={!path[1] || path[1] === "operators" ? "page" : undefined}
        >
          Operators
        </a>
        <a href="/operations" aria-current={path[1] === "operations" ? "page" : undefined}>
          Operations
        </a>
        <a href="/setups" aria-current={path[1] === "setups" ? "page" : undefined}>
          Operator setups
        </a>
        <a href="/qualification" aria-current={path[1] === "qualification" ? "page" : undefined}>
          Qualification plan
        </a>
        <a href="/discrepancies" aria-current={path[1] === "discrepancies" ? "page" : undefined}>
          Inventory discrepancies
        </a>
        <button onClick={() => setDark(!dark)}>
          {dark ? "Light appearance" : "Dark appearance"}
        </button>
      </nav>
      <main id="content">{content}</main>
    </div>
  );
}
const root = document.getElementById("admin-root");
if (root)
  createRoot(root).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
