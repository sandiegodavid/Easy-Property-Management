import { useLocation } from "react-router-dom";
import type { components } from "@epm/contracts/generated";
import { record } from "@epm/contracts/workflows";
import { ParentBackLink, SourceWorkflowLink as Link } from "../shared/home-navigation";
import { formatHomeTime } from "../shared/home-time";
import { CommandLinks, workflowUrl } from "./command";
import { useWorkspace } from "../app/workspace-gate";
import { History } from "./reads";

type Schemas = components["schemas"];
type Person = Schemas["app__modules__parties__api__router__PartyResponse"];
type Contact = Schemas["app__modules__parties__api__router__ContactResponse"];

function contactName(contact: Contact) {
  return contact.methodKind === "mailing_address"
    ? "Mailing address"
    : contact.methodKind === "email"
      ? "Email"
      : "Phone";
}

function ContactRow({
  contact,
  partyId,
  archivedParty,
}: {
  contact: Contact;
  partyId: string;
  archivedParty: boolean;
}) {
  const { scope } = useWorkspace();
  const location = useLocation();
  return (
    <li className="person-contact-row">
      <div className="person-contact-value">
        <div className="person-contact-label">
          <strong>{contactName(contact)}</strong>
          {contact.label && <span>{contact.label}</span>}
          {contact.status === "active" && contact.isPrimary && (
            <span className="person-contact-primary">Primary</span>
          )}
        </div>
        <p>
          {contact.displayValue}
          {contact.extension && ` ext. ${contact.extension}`}
        </p>
        {contact.archivedAt && <small>Archived {formatHomeTime(contact.archivedAt)}</small>}
      </div>
      {!archivedParty && (
        <div className="person-contact-actions">
          <CommandLinks
            target={partyId}
            child={contact.id}
            asButtons
            collapsible={false}
            keys={
              contact.status === "active"
                ? ["party.contact.update", "party.contact.archive"]
                : ["party.contact.restore"]
            }
            title={`Actions for ${contact.label || contactName(contact)}`}
            labels={{
              "party.contact.update": "Edit",
              "party.contact.archive": "Remove",
              "party.contact.restore": "Restore",
            }}
          />
          {scope.canWrite && contact.status === "active" && !contact.isPrimary && (
            <Link
              to={`${workflowUrl("party.contact.update", partyId, contact.id)}&setPrimary=true`}
              state={{ returnTo: location.pathname + location.search }}
            >
              Make primary
            </Link>
          )}
        </div>
      )}
    </li>
  );
}

export function ContactList({ party, allowAdd = false }: { party: Person; allowAdd?: boolean }) {
  const active = party.contactMethods?.filter((contact) => contact.status === "active") ?? [];
  const archived = party.contactMethods?.filter((contact) => contact.status === "archived") ?? [];
  return (
    <section className="person-detail-panel" aria-label="Contact details">
      <header className="person-detail-section-heading">
        <h3>Contact details</h3>
        {allowAdd && !party.archivedAt && (
          <CommandLinks
            target={party.id}
            keys={["party.contact.add"]}
            labels={{ "party.contact.add": "Add contact details" }}
            title="Add contact"
            asButtons
            collapsible={false}
          />
        )}
      </header>
      <p>
        Keep multiple emails, phone numbers and mailing addresses. Each type has one primary
        contact. To remove a primary contact with alternatives, make another contact of that type
        primary first.
      </p>
      {active.length ? (
        <ul className="person-contact-list">
          {active.map((contact) => (
            <ContactRow
              key={contact.id}
              contact={contact}
              partyId={party.id}
              archivedParty={!!party.archivedAt}
            />
          ))}
        </ul>
      ) : (
        <p className="person-detail-empty">No active contact details recorded.</p>
      )}
      {archived.length > 0 && (
        <details className="person-archived-contacts">
          <summary>Archived contacts ({archived.length})</summary>
          <ul className="person-contact-list">
            {archived.map((contact) => (
              <ContactRow
                key={contact.id}
                contact={contact}
                partyId={party.id}
                archivedParty={!!party.archivedAt}
              />
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}

export function IdentityDetail({
  party,
  tenant,
  tenantLoading,
  tenantError,
}: {
  party: Person;
  tenant: Schemas["TenantResponse"] | null | undefined;
  tenantLoading: boolean;
  tenantError?: string;
}) {
  const location = useLocation();
  const tenantPage = location.pathname === "/tenants";
  const state = record(location.state);
  const back =
    typeof state.returnTo === "string" &&
    state.returnTo.startsWith("/") &&
    !state.returnTo.startsWith("//")
      ? state.returnTo
      : "/tenants";
  const roles = { client_owner: "Owner", tenant: "Tenant", provider: "Provider" };
  const preferred = party.contactMethods?.find(
    (contact) => contact.id === tenant?.profile.preferredContactMethodId,
  );
  return (
    <section className="person-detail" aria-label="Person or organization details">
      <ParentBackLink to={back}>
        {back.startsWith("/properties?")
          ? "← Back to change ownership"
          : back.startsWith("/tenants")
            ? "← Back to Tenants"
            : "← Back to people"}
      </ParentBackLink>
      <header className="person-detail-heading">
        <div>
          <p className="person-detail-kind">
            {party.partyKind === "individual" ? "Person" : "Organization"}
          </p>
          <h2>{party.displayName}</h2>
          <div className="person-detail-badges">
            <span>{party.archivedAt ? "Archived" : "Active"}</span>
            {party.activeRoles?.map((role) => (
              <span key={role}>{roles[role]}</span>
            ))}
          </div>
        </div>
        <CommandLinks
          target={party.id}
          keys={party.archivedAt ? ["party.restore"] : ["party.patch"]}
          labels={{
            "party.patch": "Edit name",
            "party.contact.add": "Add contact details",
            "party.restore": "Restore person or organization",
          }}
          title="Contact record actions"
          asButtons
          collapsible={false}
        />
      </header>
      <p className="person-detail-intro">
        Names and contact details are shared wherever this person or organization appears in the
        app.
      </p>
      <ContactList party={party} allowAdd />
      {tenantLoading && <p role="status">Loading tenant preferences…</p>}
      {tenantError && <p role="alert">{tenantError}</p>}
      {tenant && (
        <section className="person-detail-panel" aria-label="Tenant preferences">
          <header className="person-detail-section-heading">
            <h3>Tenant preferences</h3>
            {!tenant.profile.archivedAt && (
              <CommandLinks
                target={party.id}
                keys={["tenant.profile.patch"]}
                title="Edit tenant preferences"
                asButtons
                collapsible={false}
              />
            )}
          </header>
          <p className="person-detail-intro">
            Choose which contact to use for tenant matters. Notes can include preferred contact
            times and time zone, communication channel, language or accessibility needs.
          </p>
          <dl className="person-detail-facts">
            <div>
              <dt>Preferred contact</dt>
              <dd>
                {preferred
                  ? `${contactName(preferred)} · ${preferred.displayValue}`
                  : "Not selected"}
              </dd>
            </div>
            <div>
              <dt>Contact permission</dt>
              <dd>{tenant.profile.doNotContact ? "Do not contact" : "Contact allowed"}</dd>
            </div>
            <div>
              <dt>Tenant role</dt>
              <dd>{tenant.profile.archivedAt ? "Archived" : "Active"}</dd>
            </div>
          </dl>
          {tenant.profile.notes && <p className="person-detail-notes">{tenant.profile.notes}</p>}
          <History kind="tenant_profile" id={party.id} presentation="timeline" />
        </section>
      )}
      {tenant && (
        <div className="person-tenant-lifecycle">
          <CommandLinks
            target={party.id}
            keys={tenant.profile.archivedAt ? ["tenant.restore"] : ["tenant.archive"]}
            title="Tenant lifecycle"
            asButtons
            collapsible={false}
          />
        </div>
      )}
      {!party.archivedAt && !tenantPage && (
        <section className="person-detail-more">
          <CommandLinks
            target={party.id}
            keys={[
              ...(tenant === null ? ["tenant.designate"] : []),
              ...(!party.activeRoles?.includes("provider") ? ["provider.designate"] : []),
              "party.archive",
            ]}
            title="More actions"
            labels={{
              "party.archive": "Archive person or organization",
              "tenant.designate": "Add tenant role",
              "provider.designate": "Add provider role",
            }}
          />
        </section>
      )}
      <section className="person-detail-history">
        <History kind="party" id={party.id} presentation="timeline" />
        <details className="person-record-details">
          <summary>Record details</summary>
          <dl className="person-detail-facts">
            <div>
              <dt>Revision</dt>
              <dd>{party.revision}</dd>
            </div>
            <div>
              <dt>Created</dt>
              <dd>{formatHomeTime(party.createdAt)}</dd>
            </div>
            <div>
              <dt>Last updated</dt>
              <dd>{formatHomeTime(party.updatedAt)}</dd>
            </div>
            {party.archivedAt && (
              <div>
                <dt>Archived</dt>
                <dd>{formatHomeTime(party.archivedAt)}</dd>
              </div>
            )}
          </dl>
        </details>
      </section>
    </section>
  );
}
