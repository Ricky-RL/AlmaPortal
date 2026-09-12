import type { Page } from "@playwright/test";

import { contract } from "../helpers/contract.js";
import { expect, test } from "../fixtures/test.js";

function escapeRegex(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

async function visibleSyntheticEmails(page: Page): Promise<string[]> {
  const text = await page.locator("body").innerText();
  const matches = text.match(
    new RegExp(
      `[A-Z0-9._%+-]+@${escapeRegex(contract.data.emailDomain)}`,
      "gi",
    ),
  );
  return [...new Set(matches ?? [])].sort();
}

test.describe("authenticated lead dashboard", () => {
  test("shows a recoverable error when lead loading fails", async ({
    dashboard,
  }) => {
    await dashboard.page.route("**/api/internal/leads/**", async (route) => {
      await route.fulfill({
        status: 503,
        contentType: "application/problem+json",
        body: JSON.stringify({
          detail: "Synthetic upstream failure",
        }),
      });
    });

    await dashboard.open();

    const alert = dashboard.page.getByRole("alert");
    await expect(alert).toContainText(/could not be loaded|try again/i);
    await expect(
      alert.getByRole("button", { name: /try again|retry/i }),
    ).toBeVisible();
  });

  test("lists a submitted lead with accessible landmarks", async ({
    admin,
    dashboard,
    data,
  }) => {
    const prospect = data.prospect("dashboard list");
    await admin.seedLeadList([prospect]);

    await dashboard.open();

    await expect(dashboard.main).toBeVisible();
    await expect(dashboard.navigation).toBeVisible();
    await expect(dashboard.heading).toBeVisible();
    await expect(dashboard.lead(prospect)).toBeVisible();
  });

  test("searches leads and filters by server status", async ({
    admin,
    dashboard,
    data,
  }) => {
    const pending = data.prospect("search pending");
    const reachedOut = data.prospect("search reached");
    await admin.seedLeadList([pending, reachedOut]);
    await admin.setLeadState(reachedOut.email, "REACHED_OUT");

    await dashboard.open();
    await dashboard.searchFor(pending.email);
    await expect(dashboard.lead(pending)).toBeVisible();
    await expect(dashboard.lead(reachedOut)).toBeHidden();

    await dashboard.searchFor("");
    await dashboard.filterByStatus("REACHED_OUT");
    await expect(dashboard.lead(reachedOut)).toBeVisible();
    await expect(dashboard.lead(pending)).toBeHidden();
  });

  test("moves through cursor-paginated results", async ({
    admin,
    dashboard,
    data,
  }) => {
    const prospects = Array.from(
      { length: contract.data.cursorFixtureCount },
      (_, index) => data.prospect(`cursor ${index + 1}`),
    );
    await admin.seedLeadList(prospects);

    await dashboard.open();
    await expect(dashboard.nextPage).toBeVisible();
    const firstPage = await visibleSyntheticEmails(dashboard.page);
    expect(firstPage.length).toBeGreaterThan(0);

    await dashboard.nextPage.click();
    await expect
      .poll(async () => {
        const nextPage = await visibleSyntheticEmails(dashboard.page);
        return nextPage.some((email) => !firstPage.includes(email));
      })
      .toBe(true);
  });

  test("shows lead detail, notification status, and starts CV download", async ({
    api,
    dashboard,
    data,
  }) => {
    const prospect = data.prospect("detail");
    await api.submitProspect(prospect);

    await dashboard.open();
    await dashboard.openLead(prospect);

    await expect(
      dashboard.page.getByText(prospect.email, { exact: true }),
    ).toBeVisible();
    await expect(dashboard.status("PENDING")).toBeVisible();
    await expect(
      dashboard.notificationStatus("PROVIDER_ACCEPTED"),
    ).toBeVisible();
    await dashboard.initiateCvDownload();
  });

  test("marks PENDING as REACHED_OUT and remains idempotent on refresh", async ({
    api,
    dashboard,
    data,
  }) => {
    const prospect = data.prospect("reached out");
    await api.submitProspect(prospect);

    await dashboard.open();
    await dashboard.openLead(prospect);
    await expect(dashboard.status("PENDING")).toBeVisible();
    await dashboard.markReachedOut();
    await expect(dashboard.status("REACHED_OUT")).toBeVisible();

    await dashboard.page.reload();
    await expect(dashboard.status("REACHED_OUT")).toBeVisible();
    await expect
      .poll(async () => {
        const button = dashboard.markReachedOutButton();
        return !(await button.isVisible()) || (await button.isDisabled());
      })
      .toBe(true);
  });

  test("requires confirmation before retrying an unknown notification", async ({
    admin,
    dashboard,
    data,
    sendgrid,
  }) => {
    const prospect = data.prospect("unknown notification");
    await admin.seedRetryableUnknownLead(prospect);
    await sendgrid.reset();

    await dashboard.open();
    await dashboard.openLead(prospect);
    await expect(dashboard.notificationStatus("UNKNOWN")).toBeVisible();

    await dashboard.confirmAndRetryNotification();
    await expect
      .poll(
        async () =>
          (await dashboard.notificationStatus("PENDING").isVisible()) ||
          (await dashboard
            .notificationStatus("PROVIDER_ACCEPTED")
            .isVisible()),
      )
      .toBe(true);

    await expect
      .poll(async () => (await sendgrid.messages()).length)
      .toBeGreaterThan(0);
  });
});
