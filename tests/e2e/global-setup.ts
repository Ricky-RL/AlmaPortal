import type { FullConfig } from "@playwright/test";

import { requireExternalDeliveryIsolation } from "./helpers/contract.js";
import { LocalSupabaseAdmin } from "./helpers/supabase-admin.js";
import { SendgridStub } from "./helpers/sendgrid-stub.js";

export default async function globalSetup(_config: FullConfig): Promise<void> {
  requireExternalDeliveryIsolation();

  const admin = new LocalSupabaseAdmin();
  await admin.ensureSyntheticGoogleUser();

  const sendgrid = new SendgridStub();
  await sendgrid.reset();
}
