import {
  test as base,
  expect,
  type Page,
} from "@playwright/test";

import { AlmaApiClient } from "../helpers/alma-api.js";
import { LocalSupabaseAdmin } from "../helpers/supabase-admin.js";
import { ResendStub } from "../helpers/resend-stub.js";
import { DashboardPage } from "../pages/dashboard.page.js";
import { PublicFormPage } from "../pages/public-form.page.js";
import { SyntheticData } from "./synthetic-data.js";

type AlmaFixtures = {
  admin: LocalSupabaseAdmin;
  api: AlmaApiClient;
  data: SyntheticData;
  resend: ResendStub;
  publicForm: PublicFormPage;
  authenticatedPage: Page;
  dashboard: DashboardPage;
};

export const test = base.extend<AlmaFixtures>({
  admin: async ({}, use) => {
    await use(new LocalSupabaseAdmin());
  },
  api: async ({ request }, use) => {
    await use(new AlmaApiClient(request));
  },
  data: async ({}, use, testInfo) => {
    const data = new SyntheticData(testInfo);
    await use(data);
  },
  resend: async ({}, use) => {
    const resend = new ResendStub();
    await resend.reset();
    await use(resend);
  },
  publicForm: async ({ page }, use) => {
    await use(new PublicFormPage(page));
  },
  authenticatedPage: async ({ admin, context, page }, use) => {
    await admin.installSsrSession(context);
    await use(page);
  },
  dashboard: async ({ authenticatedPage }, use) => {
    await use(new DashboardPage(authenticatedPage));
  },
});

export { expect };
