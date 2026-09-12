import { expect, type Locator, type Page } from "@playwright/test";

import type { Prospect } from "../fixtures/synthetic-data.js";
import { contract } from "../helpers/contract.js";

function exactText(value: string): RegExp {
  return new RegExp(
    `^${value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`,
    "i",
  );
}

export class DashboardPage {
  readonly main: Locator;
  readonly navigation: Locator;
  readonly heading: Locator;
  readonly search: Locator;
  readonly statusFilter: Locator;
  readonly nextPage: Locator;

  constructor(readonly page: Page) {
    this.main = page.getByRole("main");
    this.navigation = page.getByRole("navigation", {
      name: "Reviewer navigation",
    });
    this.heading = page.getByRole("heading", {
      name: "Lead review",
      level: 1,
    });
    this.search = page.getByRole("textbox", {
      name: "Search lead details",
    });
    this.statusFilter = page.getByRole("combobox", {
      name: "Filter by status",
    });
    this.nextPage = page.getByRole("button", { name: "Next" });
  }

  signOutButton(): Locator {
    return this.navigation.getByRole("button", { name: "Sign out" });
  }

  async open(): Promise<void> {
    await this.page.goto(contract.paths.dashboard);
  }

  lead(prospect: Prospect): Locator {
    const displayName = `${prospect.firstName} ${prospect.lastName}`;
    return this.page
      .getByText(exactText(prospect.email))
      .or(this.page.getByText(exactText(displayName)))
      .first();
  }

  async openLead(prospect: Prospect): Promise<void> {
    const displayName = `${prospect.firstName} ${prospect.lastName}`;
    const directLink = this.page
      .getByRole("link", {
        name: new RegExp(
          `${displayName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}|${prospect.email.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`,
          "i",
        ),
      })
      .first();
    if (await directLink.isVisible()) {
      await directLink.click();
      return;
    }

    const content = this.lead(prospect);
    const row = content.locator("xpath=ancestor::*[self::tr or @role='row'][1]");
    const rowLink = row.getByRole("link").first();
    if (await rowLink.isVisible()) {
      await rowLink.click();
    } else {
      await content.click();
    }
  }

  async searchFor(query: string): Promise<void> {
    await this.search.fill(query);
    await this.page
      .getByRole("search")
      .getByRole("button", { name: "Search" })
      .click();
  }

  async filterByStatus(status: "PENDING" | "REACHED_OUT"): Promise<void> {
    const tagName = await this.statusFilter.evaluate((element) =>
      element.tagName.toLowerCase(),
    );
    if (tagName === "select") {
      await this.statusFilter.selectOption(status);
      return;
    }

    await this.statusFilter.click();
    await this.page
      .getByRole("option", {
        name:
          status === "PENDING"
            ? /pending/i
            : /reached out|contacted/i,
      })
      .click();
  }

  status(value: "PENDING" | "REACHED_OUT"): Locator {
    const pattern =
      value === "PENDING" ? /pending/i : /reached out|reached_out|contacted/i;
    return this.page.getByText(pattern).first();
  }

  notificationStatus(
    value: "PENDING" | "PROVIDER_ACCEPTED" | "FAILED" | "UNKNOWN",
  ): Locator {
    const label = value
      .toLowerCase()
      .replaceAll("_", " ")
      .replace(/^\w/, (character) => character.toUpperCase());
    return this.page
      .getByRole("region", { name: "Notification delivery" })
      .getByText(label, { exact: true })
      .first();
  }

  markReachedOutButton(): Locator {
    return this.page.getByRole("button", {
      name: "Mark reached out",
    });
  }

  retryNotificationButton(): Locator {
    return this.page
      .getByRole("button", {
        name: "Retry notification",
      })
      .first();
  }

  async markReachedOut(): Promise<void> {
    await this.markReachedOutButton().click();
    const confirmation = this.page.getByRole("alertdialog");
    if (await confirmation.isVisible()) {
      await confirmation
        .getByRole("button", { name: "Confirm reached out" })
        .click();
    }
  }

  async confirmAndRetryNotification(): Promise<void> {
    const button = this.retryNotificationButton();
    if (await button.isDisabled()) {
      const duplicateRisk = this.page.getByRole("checkbox", {
        name: /I understand that the prior outcome is unknown.*duplicate notification/i,
      }).first();
      await expect(duplicateRisk).toBeVisible();
      await duplicateRisk.check();
    }
    await button.click();

    const dialog = this.page.getByRole("dialog");
    if (await dialog.isVisible()) {
      await dialog
        .getByRole("button", { name: /confirm|retry|send/i })
        .click();
    }
  }

  async initiateCvDownload(): Promise<void> {
    const control = this.page
      .getByRole("button", { name: "Download CV" });
    await expect(control).toBeVisible();

    const href = await control.getAttribute("href");
    let initiated = Boolean(href && href !== "#");
    const noteInitiated = () => {
      initiated = true;
    };
    this.page.once("download", noteInitiated);
    this.page.once("popup", noteInitiated);
    this.page.on("request", (request) => {
      if (
        /cv|resume|download|storage/i.test(request.url()) &&
        request.method() === "GET"
      ) {
        initiated = true;
      }
    });

    await control.click();
    await expect.poll(() => initiated).toBe(true);
  }
}
