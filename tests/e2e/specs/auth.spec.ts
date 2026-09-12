import type { Page } from "@playwright/test";

import { contract } from "../helpers/contract.js";
import { expect, test } from "../fixtures/test.js";

function signInSurface(page: Page) {
  return page
    .getByRole("heading", { name: "Sign in", level: 1 })
    .or(page.getByRole("button", { name: "Continue with Google" }))
    .first();
}

test.describe("dashboard authentication", () => {
  test("redirects an unauthenticated visitor to sign in", async ({ page }) => {
    await page.goto(contract.paths.dashboard);

    await expect
      .poll(async () => {
        const path = new URL(page.url()).pathname;
        return (
          path === contract.paths.login || (await signInSurface(page).isVisible())
        );
      })
      .toBe(true);
  });

  test("lets a reviewer sign out and return to sign in", async ({
    dashboard,
  }) => {
    await dashboard.open();
    await expect(dashboard.accountMenu()).toBeVisible();
    await expect(dashboard.signOutButton()).toBeHidden();

    await dashboard.signOut();

    await expect(signInSurface(dashboard.page)).toBeVisible();
    await expect
      .poll(() => new URL(dashboard.page.url()).pathname)
      .toBe(contract.paths.login);

    await dashboard.open();
    await expect
      .poll(async () => {
        const path = new URL(dashboard.page.url()).pathname;
        return (
          path === contract.paths.login ||
          (await signInSurface(dashboard.page).isVisible())
        );
      })
      .toBe(true);
  });

  test("handles an expired browser session by returning to sign in", async ({
    authenticatedPage,
  }) => {
    await authenticatedPage.goto(contract.paths.dashboard);
    await expect(
      authenticatedPage.getByRole("heading", {
        name: "Lead review",
        level: 1,
      }),
    ).toBeVisible();

    await authenticatedPage.context().clearCookies();
    await authenticatedPage.evaluate(() => {
      window.localStorage.clear();
      window.sessionStorage.clear();
    });
    await authenticatedPage.goto(contract.paths.dashboard);

    await expect
      .poll(async () => {
        const path = new URL(authenticatedPage.url()).pathname;
        return (
          path === contract.paths.login ||
          (await signInSurface(authenticatedPage).isVisible())
        );
      })
      .toBe(true);
  });

  test("handles a malformed SSR session without exposing the dashboard", async ({
    authenticatedPage,
  }) => {
    const context = authenticatedPage.context();
    const authCookies = (await context.cookies()).filter(
      (cookie) =>
        cookie.name.startsWith("sb-") && cookie.name.includes("auth-token"),
    );
    expect(authCookies.length).toBeGreaterThan(0);

    await context.clearCookies();
    await context.addCookies(
      authCookies.map((cookie) => ({
        ...cookie,
        value: "malformed-alma-e2e-session",
      })),
    );
    await authenticatedPage.goto(contract.paths.dashboard);

    await expect
      .poll(async () => {
        const path = new URL(authenticatedPage.url()).pathname;
        const handledError = authenticatedPage
          .getByRole("alert")
          .or(
            authenticatedPage.getByText(
              /session.*expired|authentication.*failed|sign in again/i,
            ),
          )
          .first();
        return (
          path === contract.paths.login ||
          (await handledError.isVisible())
        );
      })
      .toBe(true);
  });
});
