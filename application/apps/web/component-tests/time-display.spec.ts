import { expect, test } from "@playwright/test";

for (const browserZone of ["America/Los_Angeles", "Asia/Tokyo"]) {
  test.describe(browserZone, () => {
    test.use({ timezoneId: browserZone, locale: "en-US" });
    for (const instant of ["2026-01-02T17:00:00Z", "2026-07-02T17:00:00Z"]) {
      test(`schedules retain source time and system activity uses browser time at ${instant}`, async ({
        page,
      }) => {
        await page.goto(`/component-tests/time-display.html?at=${encodeURIComponent(instant)}`);
        const renderedTime = (zone: string) =>
          page.evaluate(
            ({ at, zone }) => {
              const formatter = new Intl.DateTimeFormat("en-US", {
                dateStyle: "medium",
                timeStyle: "short",
                timeZone: zone,
              });
              return `${formatter.format(new Date(at))} · ${zone}`;
            },
            { at: instant, zone },
          );
        const browserTime = await renderedTime(browserZone);
        await expect(page.getByTestId("system-time")).toHaveText(browserTime);
        await expect(page.getByTestId("unlinked-time")).toHaveText(browserTime);
        for (const zone of ["America/Los_Angeles", "America/Chicago", "America/New_York"]) {
          const section = page.getByRole("region", { name: zone, exact: true });
          const sourceTime = await renderedTime(zone);
          await expect(section.locator(".maintenance-appointment time")).toHaveText(sourceTime);
          await expect(section.locator(".maintenance-appointment-times")).toContainText(
            "Not specified",
          );
          await expect(section.locator(".readable-facts dd")).toHaveText([
            sourceTime,
            sourceTime,
            browserTime,
          ]);
          await expect(section.locator(".saved-item-facts dd").first()).toHaveText(sourceTime);
          await expect(section.locator(".saved-item-facts dd").last()).toHaveText(browserTime);
          await expect(section.getByTestId("home-time")).toHaveText(
            zone === browserZone ? browserTime : `${browserTime} · Source time: ${sourceTime}`,
          );
          await expect(section.getByTestId("all-day")).toHaveText(
            `Jul 2, 2026 · All day · ${zone}`,
          );
        }
      });
    }
  });
}
