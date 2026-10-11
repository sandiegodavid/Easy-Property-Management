// The Slice 50 command allowlist. Every request schema comes from OpenAPI;
// the form key names the independently registered OPS recovery contract.
export const workflowDefinitions = [
  ["portfolio.property.create", "Create property", "post", "/api/properties", null],
  [
    "portfolio.property.patch",
    "Edit property",
    "patch",
    "/api/properties/{property_id}",
    "property",
    "changes",
  ],
  [
    "portfolio.property.archive",
    "Archive property",
    "post",
    "/api/properties/{property_id}/archive",
    "property",
  ],
  [
    "portfolio.property.restore",
    "Restore property",
    "post",
    "/api/properties/{property_id}/restore",
    "property",
  ],
  [
    "portfolio.ownerships.replace",
    "Change ownership",
    "put",
    "/api/properties/{property_id}/ownerships",
    "property",
  ],
  [
    "portfolio.space.create",
    "Add office suite",
    "post",
    "/api/properties/{property_id}/spaces",
    "property",
  ],
  [
    "portfolio.space.patch",
    "Edit space",
    "patch",
    "/api/spaces/{space_id}",
    "property",
    "changes",
    "spaceId",
  ],
  [
    "portfolio.space.archive",
    "Archive space",
    "post",
    "/api/spaces/{space_id}/archive",
    "property",
    null,
    "spaceId",
  ],
  [
    "portfolio.space.restore",
    "Restore space",
    "post",
    "/api/spaces/{space_id}/restore",
    "property",
    null,
    "spaceId",
  ],
  [
    "portfolio.occupancy.change",
    "Change occupancy",
    "put",
    "/api/spaces/{space_id}/occupancy",
    "space",
  ],
  [
    "portfolio.availability.change",
    "Change availability",
    "put",
    "/api/spaces/{space_id}/availability",
    "space",
  ],
  [
    "portfolio.space.classify",
    "Classify space",
    "put",
    "/api/spaces/{space_id}/classification",
    "space",
  ],
  [
    "portfolio.occupancy.cancel",
    "Cancel scheduled occupancy",
    "post",
    "/api/spaces/{space_id}/occupancy/scheduled/{period_id}/cancel",
    "space",
    null,
    "periodId",
  ],
  [
    "portfolio.occupancy.replace",
    "Replace scheduled occupancy",
    "put",
    "/api/spaces/{space_id}/occupancy/scheduled/{period_id}/replace",
    "space",
    null,
    "periodId",
  ],
  [
    "portfolio.occupancy.reschedule",
    "Reschedule occupancy",
    "put",
    "/api/spaces/{space_id}/occupancy/scheduled/{period_id}/reschedule",
    "space",
    null,
    "periodId",
  ],
  [
    "portfolio.occupancy.correct",
    "Correct occupancy",
    "post",
    "/api/spaces/{space_id}/occupancy/{period_id}/correct",
    "space",
    "occupancy",
    "periodId",
  ],
  ["party.create", "Create identity", "post", "/api/parties", null],
  ["party.patch", "Edit identity", "patch", "/api/parties/{party_id}", "party"],
  ["party.archive", "Archive identity", "post", "/api/parties/{party_id}/archive", "party"],
  ["party.restore", "Restore identity", "post", "/api/parties/{party_id}/restore", "party"],
  ["party.contact.add", "Add contact", "post", "/api/parties/{party_id}/contact-methods", "party"],
  [
    "party.contact.update",
    "Edit contact",
    "patch",
    "/api/parties/{party_id}/contact-methods/{method_id}",
    "party",
    null,
    "methodId",
  ],
  [
    "party.contact.archive",
    "Archive contact",
    "post",
    "/api/parties/{party_id}/contact-methods/{method_id}/archive",
    "party",
    null,
    "methodId",
  ],
  [
    "party.contact.restore",
    "Restore contact",
    "post",
    "/api/parties/{party_id}/contact-methods/{method_id}/restore",
    "party",
    null,
    "methodId",
  ],
  ["tenant.create", "Create tenant", "post", "/api/tenants", null],
  [
    "tenant.designate",
    "Use identity as tenant",
    "post",
    "/api/tenants/from-party/{party_id}",
    "tenant",
  ],
  ["tenant.profile.patch", "Edit tenant preferences", "patch", "/api/tenants/{party_id}", "tenant"],
  ["tenant.archive", "Archive tenant", "post", "/api/tenants/{party_id}/archive", "tenant"],
  ["tenant.restore", "Restore tenant", "post", "/api/tenants/{party_id}/restore", "tenant"],
  ["provider.create", "Create provider", "post", "/api/providers", null],
  [
    "provider.designate",
    "Use identity as provider",
    "post",
    "/api/providers/from-party/{party_id}",
    "provider",
  ],
  [
    "provider.profile.patch",
    "Edit provider profile",
    "patch",
    "/api/providers/{party_id}",
    "provider",
  ],
  ["provider.archive", "Archive provider", "post", "/api/providers/{party_id}/archive", "provider"],
  ["provider.restore", "Restore provider", "post", "/api/providers/{party_id}/restore", "provider"],
  [
    "provider.category.create",
    "Create provider category",
    "post",
    "/api/provider-categories",
    null,
  ],
  [
    "provider.category.patch",
    "Edit provider category",
    "patch",
    "/api/provider-categories/{category_id}",
    "provider_category",
  ],
  [
    "provider.category.archive",
    "Archive provider category",
    "post",
    "/api/provider-categories/{category_id}/archive",
    "provider_category",
  ],
  [
    "provider.category.restore",
    "Restore provider category",
    "post",
    "/api/provider-categories/{category_id}/restore",
    "provider_category",
  ],
  [
    "provider.category_assignment.assign",
    "Assign category",
    "post",
    "/api/providers/{party_id}/category-assignments",
    "provider",
  ],
  [
    "provider.category_assignment.archive",
    "Archive category assignment",
    "post",
    "/api/providers/{party_id}/category-assignments/{assignment_id}/archive",
    "provider",
    null,
    "assignmentId",
  ],
  [
    "provider.category_assignment.restore",
    "Restore category assignment",
    "post",
    "/api/providers/{party_id}/category-assignments/{assignment_id}/restore",
    "provider",
    null,
    "assignmentId",
  ],
  ...[
    ["service", "service", "services", "item_id"],
    ["area", "service area", "service-areas", "item_id"],
    ["work_history", "work history", "work-history", "item_id"],
    ["reference", "reference", "references", "item_id"],
    ["reputation_link", "reputation link", "reputation-links", "link_id"],
  ].flatMap(([key, label, segment, parameter]) => [
    [
      `provider.${key}.add`,
      `Add ${label}`,
      "post",
      `/api/providers/{party_id}/${segment}`,
      "provider",
    ],
    [
      `provider.${key}.update`,
      `Edit ${label}`,
      "patch",
      `/api/providers/{party_id}/${segment}/{${parameter}}`,
      "provider",
      null,
      "itemId",
    ],
    [
      `provider.${key}.archive`,
      `Archive ${label}`,
      "post",
      `/api/providers/{party_id}/${segment}/{${parameter}}/archive`,
      "provider",
      null,
      "itemId",
    ],
    [
      `provider.${key}.restore`,
      `Restore ${label}`,
      "post",
      `/api/providers/{party_id}/${segment}/{${parameter}}/restore`,
      "provider",
      null,
      "itemId",
    ],
  ]),
];

export function workflowContracts(openapi) {
  const inline = (schema) => {
    if (schema.$ref) return inline(openapi.components.schemas[schema.$ref.split("/").at(-1)]);
    return Object.fromEntries(
      Object.entries(schema).map(([key, value]) => [
        key,
        key === "properties"
          ? Object.fromEntries(Object.entries(value).map(([name, child]) => [name, inline(child)]))
          : key === "items"
            ? inline(value)
            : key === "anyOf" || key === "oneOf"
              ? value.map(inline)
              : value,
      ]),
    );
  };
  return (
    JSON.stringify(
      workflowDefinitions.map(([formKey, title, method, path, sourceKind, nesting, childKey]) => {
        if (!openapi.components.schemas.RecoveryInput.properties.formKey.enum.includes(formKey))
          throw new Error(`Unregistered OPS form: ${formKey}`);
        const operation = openapi.paths[path][method];
        return {
          formKey,
          title,
          method,
          path,
          sourceKind,
          nesting: nesting ?? null,
          childKey: childKey ?? null,
          operationId: operation.operationId,
          schema: inline(operation.requestBody.content["application/json"].schema),
        };
      }),
      null,
      2,
    ) + "\n"
  );
}

export function workflowDispatch(openapi) {
  const cases = workflowDefinitions
    .map(([key, , method, path, , , childKey]) => {
      const schema = openapi.paths[path][method].requestBody.content["application/json"].schema.$ref
        .split("/")
        .at(-1);
      const placeholders = [...path.matchAll(/\{([^}]+)\}/g)];
      const parameters = placeholders.map(
        (match, index) =>
          `${match[1]}: ${index === 0 && !(childKey && placeholders.length === 1) ? "target" : "child"}`,
      );
      return `    case ${JSON.stringify(key)}: return api.${method.toUpperCase()}(${JSON.stringify(path)}, { ${parameters.length ? `params: { path: { ${parameters.join(", ")} } }, ` : ""}body: body as components["schemas"][${JSON.stringify(schema)}] });`;
    })
    .join("\n");
  return `// Generated by npm run contracts:generate. Do not edit.\nimport { api } from "../client";\nimport type { components } from "./schema";\nimport { workflows, validateRequest } from "../workflows";\n\n/** Runtime validation precedes the generated type assertion for recovered JSON. */\nexport function dispatchWorkflow(key: string, target: string, child: string, body: Record<string, unknown>) {\n  const definition = workflows.find((item) => item.formKey === key);\n  if (!definition) throw new Error("Unknown workflow.");\n  validateRequest(definition.schema, body);\n  switch (key) {\n${cases}\n    default: throw new Error("Unsupported workflow.");\n  }\n}\n`;
}
