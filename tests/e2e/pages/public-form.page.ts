import type { Locator, Page } from "@playwright/test";

import type { Prospect, UploadFixture } from "../fixtures/synthetic-data.js";
import { contract } from "../helpers/contract.js";

export class PublicFormPage {
  readonly main: Locator;
  readonly form: Locator;
  readonly firstName: Locator;
  readonly lastName: Locator;
  readonly email: Locator;
  readonly comments: Locator;
  readonly cv: Locator;
  readonly acknowledgement: Locator;
  readonly submit: Locator;

  constructor(readonly page: Page) {
    this.main = page.getByRole("main");
    this.form = page.locator("form").first();
    this.firstName = page.getByRole("textbox", { name: "First name" });
    this.lastName = page.getByRole("textbox", { name: "Last name" });
    this.email = page.getByRole("textbox", { name: "Email" });
    this.comments = page.getByRole("textbox", { name: /comments/i });
    this.cv = page.getByLabel("Resume or CV");
    this.acknowledgement = page.getByRole("checkbox", {
      name: /I confirm that all entered details.*synthetic.*no real PII/i,
    });
    this.submit = page.getByRole("button", {
      name: "Submit synthetic lead",
    });
  }

  async open(): Promise<void> {
    await this.page.goto(contract.paths.publicForm);
  }

  async fill(
    prospect: Prospect,
    options: { acknowledge?: boolean; file?: UploadFixture } = {},
  ): Promise<void> {
    await this.firstName.fill(prospect.firstName);
    await this.lastName.fill(prospect.lastName);
    await this.email.fill(prospect.email);
    if (prospect.comments) {
      await this.comments.fill(prospect.comments);
    }
    await this.cv.setInputFiles(options.file ?? prospect.cv);
    if (options.acknowledge ?? prospect.acknowledged) {
      await this.acknowledgement.check();
    } else {
      await this.acknowledgement.uncheck();
    }
  }

  async submitForm(): Promise<void> {
    await this.submit.click();
  }

  successMessage(): Locator {
    return this.page
      .getByRole("heading", {
        name: "Submission received",
      })
      .or(
        this.page.getByRole("status").filter({
          hasText: /thank|success|submitted|received/i,
        }),
      )
      .or(
        this.page.getByText(
          /thank you|successfully submitted|submission received/i,
        ),
      )
      .first();
  }

  async submissionSucceeded(): Promise<boolean> {
    const successPath = contract.paths.success;
    const currentPath = new URL(this.page.url()).pathname;
    const routedSuccess =
      successPath !== undefined &&
      (currentPath === successPath ||
        currentPath.startsWith(`${successPath}/`));
    return routedSuccess || (await this.successMessage().isVisible());
  }

  validationMessage(pattern: RegExp): Locator {
    return this.form
      .getByRole("alert")
      .filter({ hasText: pattern })
      .or(this.page.getByText(pattern))
      .first();
  }
}
