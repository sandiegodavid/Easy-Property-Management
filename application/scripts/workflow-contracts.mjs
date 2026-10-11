// Delivered browser command allowlist. Every request schema comes from OpenAPI;
// the form key names the independently registered OPS recovery contract.
export const workflowDefinitions = [
  ["file.upload", "Attach supporting evidence", "post", "/api/files", null],
  [
    "finance.rent_expectation.synchronize",
    "Synchronize rent schedule",
    "post",
    "/api/leases/{lease_id}/rent-expectations/synchronize",
    "lease",
  ],
  [
    "finance.rent_expectation.void",
    "Void rent expectation",
    "post",
    "/api/rent-expectations/{expectation_id}/void",
    "lease",
    null,
    "expectationId",
  ],
  [
    "finance.rent_expectation.timeliness_review",
    "Review rent timeliness",
    "post",
    "/api/rent-expectations/{expectation_id}/timeliness-reviews",
    "lease",
    null,
    "expectationId",
  ],
  ["finance.rent_receipt.create", "Record rent receipt", "post", "/api/rent-receipts", "lease"],
  [
    "finance.rent_receipt.void",
    "Void rent receipt",
    "post",
    "/api/rent-receipts/{receipt_id}/void",
    "lease",
    null,
    "receiptId",
  ],
  [
    "finance.prepaid_check.create",
    "Schedule prepaid check",
    "post",
    "/api/prepaid-checks",
    "lease",
  ],
  ...["deposit", "return", "void", "replace"].map((action) => [
    `finance.prepaid_check.${action}`,
    `${action[0].toUpperCase()}${action.slice(1)} prepaid check`,
    "post",
    `/api/prepaid-checks/{check_id}/${action}`,
    "lease",
    null,
    "prepaidCheckId",
  ]),
  ["finance.expense.create", "Record paid expense", "post", "/api/expenses", null],
  [
    "finance.expense.patch",
    "Edit expense context",
    "patch",
    "/api/expenses/{expense_id}",
    "expense",
    "financialChanges",
  ],
  ["finance.expense.void", "Void expense", "post", "/api/expenses/{expense_id}/void", "expense"],
  [
    "finance.expense_refund.create",
    "Record expense refund",
    "post",
    "/api/expenses/{expense_id}/refunds",
    "expense",
  ],
  [
    "finance.expense_refund.void",
    "Void expense refund",
    "post",
    "/api/expense-refunds/{refund_id}/void",
    "expense",
    null,
    "targetId",
  ],
  [
    "finance.expense_category.create",
    "Create expense category",
    "post",
    "/api/expense-categories",
    null,
  ],
  [
    "finance.expense_category.patch",
    "Edit expense category",
    "patch",
    "/api/expense-categories/{category_id}",
    "expense_category",
    "financialChanges",
  ],
  ...["archive", "restore"].map((action) => [
    `finance.expense_category.${action}`,
    `${action[0].toUpperCase()}${action.slice(1)} expense category`,
    "post",
    `/api/expense-categories/{category_id}/${action}`,
    "expense_category",
  ]),
  [
    "finance.deposit_account.create",
    "Create deposit account",
    "post",
    "/api/leases/{lease_id}/security-deposit",
    null,
  ],
  [
    "finance.deposit_receipt.create",
    "Record deposit receipt",
    "post",
    "/api/security-deposits/{account_id}/receipts",
    "security_deposit_account",
  ],
  [
    "finance.deposit_receipt.void",
    "Void deposit receipt",
    "post",
    "/api/security-deposit-receipts/{receipt_id}/void",
    "security_deposit_account",
    null,
    "targetId",
  ],
  [
    "finance.deposit_settlement.create",
    "Prepare deposit settlement",
    "post",
    "/api/security-deposits/{account_id}/settlements",
    "security_deposit_account",
  ],
  [
    "finance.deposit_settlement.patch",
    "Edit deposit settlement",
    "patch",
    "/api/security-deposit-settlements/{settlement_id}",
    "security_deposit_account",
    "financialChanges",
    "targetId",
  ],
  ...["approve", "complete", "void"].map((action) => [
    `finance.deposit_settlement.${action}`,
    `${action[0].toUpperCase()}${action.slice(1)} deposit settlement`,
    "post",
    `/api/security-deposit-settlements/{settlement_id}/${action}`,
    "security_deposit_account",
    null,
    "targetId",
  ]),
  ...["deduction", "credit"].flatMap((kind) => [
    [
      `finance.deposit_${kind}.create`,
      `Add settlement ${kind}`,
      "post",
      `/api/security-deposit-settlements/{settlement_id}/${kind}s`,
      "security_deposit_account",
      null,
      "targetId",
    ],
    [
      `finance.deposit_${kind}.update`,
      `Edit settlement ${kind}`,
      "patch",
      `/api/security-deposit-${kind}s/{${kind}_id}`,
      "security_deposit_account",
      null,
      "targetId",
    ],
    [
      `finance.deposit_${kind}.delete`,
      `Delete settlement ${kind}`,
      "delete",
      `/api/security-deposit-${kind}s/{${kind}_id}`,
      "security_deposit_account",
      null,
      "targetId",
    ],
  ]),
  [
    "finance.deposit_deduction_source.add",
    "Add deduction source",
    "post",
    "/api/security-deposit-deductions/{deduction_id}/sources",
    "security_deposit_account",
    null,
    "targetId",
  ],
  [
    "finance.deposit_deduction_source.delete",
    "Delete deduction source",
    "delete",
    "/api/security-deposit-deduction-sources/{source_id}",
    "security_deposit_account",
    null,
    "targetId",
  ],
  [
    "finance.deposit_refund.create",
    "Record deposit refund",
    "post",
    "/api/security-deposit-settlements/{settlement_id}/refunds",
    "security_deposit_account",
    null,
    "targetId",
  ],
  [
    "finance.deposit_refund.void",
    "Void deposit refund",
    "post",
    "/api/security-deposit-refunds/{refund_id}/void",
    "security_deposit_account",
    null,
    "targetId",
  ],
  ["owner_rent_report.create", "Record owner rent report", "post", "/api/owner-rent-reports", null],
  [
    "owner_rent_report.patch",
    "Edit owner rent report",
    "patch",
    "/api/owner-rent-reports/{report_id}",
    "owner_rent_report",
    "financialChanges",
  ],
  [
    "owner_rent_report.verify",
    "Verify owner rent report",
    "post",
    "/api/owner-rent-reports/{report_id}/verify",
    "owner_rent_report",
  ],
  [
    "owner_rent_report.reject",
    "Reject owner rent report",
    "post",
    "/api/owner-rent-reports/{report_id}/reject",
    "owner_rent_report",
  ],
  [
    "file.link.archive",
    "Archive evidence link",
    "post",
    "/api/file-links/{link_id}/archive",
    "file_link",
  ],
  ["lease.create", "Create lease draft", "post", "/api/leases", null],
  ["lease.patch", "Edit lease draft", "patch", "/api/leases/{lease_id}", "lease"],
  [
    "lease.term.replace",
    "Replace draft rent terms",
    "put",
    "/api/leases/{lease_id}/initial-term",
    "lease",
  ],
  [
    "lease.participant.add",
    "Add lease participant",
    "post",
    "/api/leases/{lease_id}/participants",
    "lease",
  ],
  [
    "lease.participant.update",
    "Edit lease participant",
    "patch",
    "/api/leases/{lease_id}/participants/{participant_id}",
    "lease",
    null,
    "participantId",
  ],
  [
    "lease.participant.remove",
    "Remove lease participant",
    "delete",
    "/api/leases/{lease_id}/participants/{participant_id}",
    "lease",
    null,
    "participantId",
  ],
  ...["execute", "end", "terminate", "void"].map((action) => [
    `lease.${action}`,
    `${action[0].toUpperCase()}${action.slice(1)} lease`,
    "post",
    `/api/leases/{lease_id}/${action}`,
    "lease",
  ]),
  [
    "lease.renewal.add",
    "Add renewal option",
    "post",
    "/api/leases/{lease_id}/renewal-options",
    "lease",
  ],
  [
    "lease.renewal.update",
    "Edit renewal option",
    "patch",
    "/api/leases/{lease_id}/renewal-options/{option_id}",
    "lease",
    null,
    "optionId",
  ],
  [
    "lease.renewal.decide",
    "Decide renewal option",
    "patch",
    "/api/leases/{lease_id}/renewal-options/{option_id}",
    "lease",
    null,
    "optionId",
  ],
  [
    "lease.termination.create",
    "Request termination",
    "post",
    "/api/leases/{lease_id}/termination-cases",
    "lease",
  ],
  [
    "lease.termination.proposal.add",
    "Add termination proposal",
    "post",
    "/api/termination-cases/{case_id}/proposals",
    "lease",
    null,
    "caseId",
  ],
  [
    "lease.termination.proposal.accept",
    "Accept termination proposal",
    "post",
    "/api/termination-cases/{case_id}/accept",
    "lease",
    null,
    "caseId",
  ],
  [
    "lease.termination.transition",
    "Review termination request",
    "patch",
    "/api/termination-cases/{case_id}",
    "lease",
    null,
    "caseId",
  ],
  [
    "lease.termination.complete",
    "Complete termination",
    "post",
    "/api/termination-cases/{case_id}/complete",
    "lease",
    null,
    "caseId",
  ],
  [
    "inspection.report.create",
    "Create inspection draft",
    "post",
    "/api/leases/{lease_id}/condition-reports",
    "inspection_lease",
  ],
  [
    "inspection.report.patch",
    "Edit inspection draft",
    "patch",
    "/api/condition-reports/{report_id}",
    "condition_report",
  ],
  [
    "inspection.report.areas.replace",
    "Edit inspection checklist",
    "put",
    "/api/condition-reports/{report_id}/areas",
    "condition_report",
  ],
  [
    "inspection.report.acknowledge",
    "Record inspection acknowledgments",
    "put",
    "/api/condition-reports/{report_id}/acknowledgments",
    "condition_report",
  ],
  [
    "inspection.report.finalize",
    "Finalize inspection",
    "post",
    "/api/condition-reports/{report_id}/finalize",
    "condition_report",
  ],
  [
    "inspection.report.correct",
    "Correct finalized inspection",
    "post",
    "/api/condition-reports/{report_id}/corrections",
    "condition_report",
  ],
  [
    "inspection.evidence.attach",
    "Attach inspection evidence",
    "post",
    "/api/condition-observations/{observation_id}/evidence",
    "condition_observation",
  ],
  [
    "inspection.comparison.review",
    "Review condition comparison",
    "put",
    "/api/leases/{lease_id}/condition-comparison",
    "inspection_lease",
  ],
  [
    "inspection.template.create",
    "Create inspection template",
    "post",
    "/api/condition-checklist-templates",
    null,
  ],
  [
    "inspection.template.patch",
    "Edit inspection template",
    "patch",
    "/api/condition-checklist-templates/{template_id}",
    "condition_template",
  ],
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
          : key === "items" || (key === "additionalProperties" && typeof value === "object")
            ? inline(value)
            : key === "anyOf" || key === "oneOf"
              ? value.map(inline)
              : value,
      ]),
    );
  };
  return (
    JSON.stringify(
      workflowDefinitions
        .map(([formKey, title, method, path, sourceKind, nesting, childKey]) => {
          if (!openapi.components.schemas.RecoveryInput.properties.formKey.enum.includes(formKey))
            throw new Error(`Unregistered OPS form: ${formKey}`);
          const sources = openapi.components.schemas.RecoveryInput.properties.sourceKind.anyOf;
          if (sourceKind && !sources.some((entry) => entry.enum?.includes(sourceKind)))
            throw new Error(`Unsupported recovery source for ${formKey}: ${sourceKind}`);
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
            schema:
              formKey === "inspection.evidence.attach" || formKey === "file.upload"
                ? {
                    type: "object",
                    additionalProperties: false,
                    required: [
                      "purpose",
                      "expectedRevision",
                      "idempotencyKey",
                      "originalName",
                      "mediaType",
                      "sizeBytes",
                      "contentSha256",
                      ...(formKey === "file.upload" ? ["entityType", "entityId"] : []),
                    ],
                    properties: {
                      purpose: inline(operation.requestBody.content["multipart/form-data"].schema)
                        .properties.purpose,
                      ...(formKey === "file.upload"
                        ? {
                            entityType: {
                              type: "string",
                              enum: ["expense", "owner_rent_report", "security_deposit_deduction"],
                            },
                            entityId: { type: "string", format: "uuid" },
                          }
                        : {}),
                      expectedRevision: { type: "integer", minimum: 0 },
                      idempotencyKey: { type: "string", format: "uuid" },
                      originalName: { type: "string", minLength: 1, maxLength: 255 },
                      mediaType: { type: "string", minLength: 1, maxLength: 255 },
                      sizeBytes: { type: "integer", minimum: 1, maximum: 50 * 1024 * 1024 },
                      contentSha256: { type: "string", pattern: "^[0-9a-f]{64}$" },
                    },
                  }
                : inline(operation.requestBody.content["application/json"].schema),
          };
        })
        .map((definition) => {
          if (definition.formKey === "finance.deposit_account.create") {
            definition.schema.properties.leaseId = { type: "string", format: "uuid" };
            definition.schema.required.push("leaseId");
          }
          if (definition.formKey === "lease.renewal.update")
            definition.schema.properties = Object.fromEntries(
              Object.entries(definition.schema.properties).filter(
                ([key]) => !["status", "decidedOn"].includes(key),
              ),
            );
          if (definition.formKey === "lease.renewal.decide") {
            definition.schema.properties = Object.fromEntries(
              Object.entries(definition.schema.properties).filter(([key]) =>
                [
                  "status",
                  "decidedOn",
                  "notes",
                  "expectedLeaseRevision",
                  "idempotencyKey",
                ].includes(key),
              ),
            );
            definition.schema.required = [
              "status",
              "decidedOn",
              "expectedLeaseRevision",
              "idempotencyKey",
            ];
          }
          return definition;
        }),
      null,
      2,
    ) + "\n"
  );
}

export function workflowDispatch(openapi) {
  const cases = workflowDefinitions
    .map(([key, , method, path, , , childKey]) => {
      if (key === "inspection.evidence.attach" || key === "file.upload")
        return `    case ${JSON.stringify(key)}: throw new Error("Reselect verified evidence in the inspection editor.");`;
      const schema = openapi.paths[path][method].requestBody.content["application/json"].schema.$ref
        .split("/")
        .at(-1);
      const placeholders = [...path.matchAll(/\{([^}]+)\}/g)];
      const parameters = placeholders.map(
        (match, index) =>
          `${match[1]}: ${key === "finance.deposit_account.create" ? "String(body.leaseId)" : index === 0 && !(childKey && placeholders.length === 1) ? "target" : "child"}`,
      );
      if (key === "finance.deposit_account.create")
        return `    case ${JSON.stringify(key)}: { const { leaseId, ...request } = body; return api.POST(${JSON.stringify(path)}, { params: { path: { lease_id: String(leaseId) } }, body: request as components["schemas"][${JSON.stringify(schema)}] }); }`;
      return `    case ${JSON.stringify(key)}: return api.${method.toUpperCase()}(${JSON.stringify(path)}, { ${parameters.length ? `params: { path: { ${parameters.join(", ")} } }, ` : ""}body: body as components["schemas"][${JSON.stringify(schema)}] });`;
    })
    .join("\n");
  return `// Generated by npm run contracts:generate. Do not edit.\nimport { api } from "../client";\nimport type { components } from "./schema";\nimport { workflows, validateRequest } from "../workflows";\n\n/** Runtime validation precedes the generated type assertion for recovered JSON. */\nexport function dispatchWorkflow(key: string, target: string, child: string, body: Record<string, unknown>) {\n  const definition = workflows.find((item) => item.formKey === key);\n  if (!definition) throw new Error("Unknown workflow.");\n  validateRequest(definition.schema, body);\n  switch (key) {\n${cases}\n    default: throw new Error("Unsupported workflow.");\n  }\n}\n`;
}
