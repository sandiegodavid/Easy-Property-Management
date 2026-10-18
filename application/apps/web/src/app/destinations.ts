export const destinations = [
  { id: "home", label: "Home", route: "/home", icon: "home", capability: null, fixed: true },
  {
    id: "properties",
    label: "Properties",
    route: "/properties",
    icon: "building",
    capability: "operator.property-directory",
    fixed: false,
  },
  {
    id: "owners",
    label: "Owners",
    route: "/owners",
    icon: "people",
    capability: "operator.owner-directory",
    fixed: false,
  },
  {
    id: "renters",
    label: "Tenants",
    route: "/tenants",
    icon: "people",
    capability: "operator.context-overviews",
    fixed: false,
  },
  {
    id: "leasing",
    label: "Leasing",
    route: "/leasing",
    icon: "key",
    capability: "operator.context-overviews",
    fixed: false,
  },
  {
    id: "money",
    label: "Money",
    route: "/money",
    icon: "wallet",
    capability: "operator.context-overviews",
    fixed: false,
  },
  {
    id: "maintenance",
    label: "Maintenance",
    route: "/maintenance",
    icon: "tools",
    capability: "operator.context-overviews",
    fixed: false,
  },
  {
    id: "providers",
    label: "Providers",
    route: "/providers",
    icon: "people",
    capability: "operator.context-overviews",
    fixed: false,
  },
  {
    id: "settings",
    label: "Settings",
    route: "/settings",
    icon: "settings",
    capability: null,
    fixed: true,
  },
] as const;

export type DestinationId = (typeof destinations)[number]["id"];
export const defaultOrder = destinations.map((destination) => destination.id);
export function destination(id: string) {
  return destinations.find((item) => item.id === id);
}

export const propertySections = [
  "overview",
  "units",
  "leases",
  "money",
  "maintenance",
  "conversations",
  "documents",
  "setup",
] as const;
export const ownerSections = [
  "overview",
  "properties",
  "leases",
  "money",
  "maintenance",
  "conversations",
  "details",
] as const;
type ContextTarget =
  | { kind: "property"; id: string; section?: (typeof propertySections)[number] }
  | { kind: "owner"; id: string; section?: (typeof ownerSections)[number] };

export function contextPath(target: ContextTarget) {
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(target.id))
    return "/home";
  return `/${target.kind === "property" ? "properties" : "owners"}/${target.id}/${target.section ?? "overview"}`;
}
