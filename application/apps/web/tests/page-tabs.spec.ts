import { expect, test, type Locator } from "@playwright/test";
import type { components } from "@epm/contracts/generated";
import axe from "axe-core";

test.use({ extraHTTPHeaders: { Origin: "http://127.0.0.1:18744" } });

async function appearance(item: Locator) {
  return item.evaluate((element) => {
    const css = getComputedStyle(element);
    return {
      background: css.backgroundColor,
      color: css.color,
      border: css.borderBottomColor,
      borderWidth: css.borderBottomWidth,
      radius: css.borderRadius,
      padding: css.padding,
      weight: css.fontWeight,
    };
  });
}

test("page navigation shares Property Detail tab styling and scrolls within narrow viewports", async ({
  page,
  request,
}, testInfo) => {
  const response = await request.post("/api/properties", {
    data: {
      displayName: "Shared tab styles",
      addressLine1: "10 Maple Street",
      city: "Portland",
      region: "OR",
      countryCode: "US",
      propertyType: "single_family_home",
      expectedPropertyRevision: 0,
      idempotencyKey: crypto.randomUUID(),
      ownerships: [
        {
          ownerKind: "client_owner",
          inlineParty: {
            partyKind: "individual",
            displayName: "Tab style owner",
          },
        },
      ],
    },
  });
  expect(response.ok(), await response.text()).toBe(true);
  const property = (await response.json()) as components["schemas"]["PropertyMutationResponse"];
  const ownerId = property.ownerships[0].partyId!;
  for (const theme of ["light", "dark"]) {
    await page.goto(`/properties/${property.id}/overview`);
    await page.evaluate((value) => {
      document.documentElement.dataset.theme = value;
    }, theme);
    const reference = page.getByRole("navigation", { name: "property sections", exact: true });
    await expect(reference.locator('[aria-current="page"]')).toHaveText("Overview");
    const expected = await appearance(reference.locator('[aria-current="page"]'));
    for (const width of [1280, 390]) {
      await page.setViewportSize({ width, height: 900 });
      for (const view of [
        {
          path: `/properties/${property.id}/overview`,
          nav: "property sections",
          active: "Overview",
          next: "Property setup",
        },
        {
          path: `/owners/${ownerId}/overview`,
          nav: "owner sections",
          active: "Overview",
          next: "Money",
        },
        { path: "/money", nav: "Money views", active: "Rent", next: "Reporting" },
        { path: "/tasks", nav: "Work views", active: "Tasks", next: "Conversations" },
        {
          path: "/conversations?intake=true",
          nav: "Source views",
          active: "Retained sources",
          next: "Recorded conversations",
        },
      ]) {
        await page.goto(view.path);
        await page.evaluate((value) => {
          document.documentElement.dataset.theme = value;
        }, theme);
        const nav = page.getByRole("navigation", { name: view.nav, exact: true });
        await expect(nav).toHaveClass(/page-tabs/);
        const active = nav.locator('[aria-current="page"]');
        await expect(active).toHaveCount(1);
        await expect(active).toHaveText(view.active);
        expect(await appearance(active)).toEqual(expected);
        await active.focus();
        await expect(active).toHaveCSS("outline-style", "solid");
        await expect(active).toHaveCSS("outline-width", "3px");
        expect(await nav.evaluate((element) => getComputedStyle(element).flexWrap)).toBe("nowrap");
        expect(
          await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
        ).toBe(true);
        await nav.screenshot({ path: testInfo.outputPath(`${view.nav}-${theme}-${width}.png`) });
        const next = nav.getByRole("link", { name: view.next, exact: true });
        await next.scrollIntoViewIfNeeded();
        if (width === 390 && view.nav === "property sections") {
          expect(await nav.evaluate((element) => element.scrollWidth > element.clientWidth)).toBe(
            true,
          );
          expect(await nav.evaluate((element) => element.scrollLeft)).toBeGreaterThan(0);
        }
        await next.click();
        const destination =
          view.nav === "Source views"
            ? page.getByRole("navigation", { name: "Work views", exact: true })
            : nav;
        await expect(destination.locator('[aria-current="page"]')).toHaveText(
          view.next === "Recorded conversations" ? "Conversations" : view.next,
        );
      }
    }
  }
  await page.goto("/properties");
  await expect(page.getByRole("navigation", { name: "Property status filters" })).not.toHaveClass(
    /page-tabs/,
  );
});

test("Home uses shared tabs without losing arrow-key selection or panel semantics", async ({
  page,
}, testInfo) => {
  await page.goto("/home");
  const tabs = page.getByRole("tablist", { name: "Work queue", exact: true });
  await expect(tabs).toHaveClass(/page-tabs/);
  for (const theme of ["light", "dark"]) {
    await page.evaluate((value) => {
      document.documentElement.dataset.theme = value;
    }, theme);
    for (const width of [1280, 390]) {
      await page.setViewportSize({ width, height: 900 });
      const first = tabs.getByRole("tab", { name: "Needs action", exact: true });
      await first.click();
      await page.keyboard.press("ArrowRight");
      const waiting = tabs.getByRole("tab", { name: "Waiting", exact: true });
      await expect(waiting).toBeFocused();
      await expect(waiting).toHaveAttribute("aria-selected", "true");
      await expect(tabs.locator('[aria-selected="true"]')).toHaveCount(1);
      await expect(page.getByRole("tabpanel", { name: "Waiting", exact: true })).toBeVisible();
      await page.keyboard.press("End");
      await expect(tabs.getByRole("tab", { name: "Upcoming", exact: true })).toBeFocused();
      await page.keyboard.press("Home");
      await expect(first).toBeFocused();
      await expect(first).toHaveCSS("border-bottom-width", "2px");
      await tabs.screenshot({ path: testInfo.outputPath(`home-tabs-${theme}-${width}.png`) });
      await page.evaluate(axe.source);
      const violations = await page.evaluate(async () =>
        (
          await window.axe.run(".home-tabs", {
            runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21aa"] },
          })
        ).violations.map((item) => item.id),
      );
      expect(violations).toEqual([]);
    }
  }
});
