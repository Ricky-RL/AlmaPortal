import { expect, test } from "../fixtures/test.js";

test.describe("@mobile responsive critical paths", () => {
  test("keeps the public form usable at a phone viewport", async ({
    data,
    publicForm,
  }) => {
    const prospect = data.prospect("mobile form");
    await publicForm.open();

    expect(publicForm.page.viewportSize()?.width).toBeLessThanOrEqual(600);
    await expect(publicForm.main).toBeVisible();
    await expect(
      publicForm.page.getByRole("heading", { level: 1 }),
    ).toBeVisible();
    await expect(publicForm.form).toBeVisible();
    await publicForm.fill(prospect);
    await expect(publicForm.submit).toBeVisible();
  });

  test("keeps the lead dashboard usable at a phone viewport", async ({
    admin,
    dashboard,
    data,
  }) => {
    const prospect = data.prospect("mobile dashboard");
    await admin.seedLeadList([prospect]);
    await dashboard.open();

    expect(dashboard.page.viewportSize()?.width).toBeLessThanOrEqual(600);
    await expect(dashboard.main).toBeVisible();
    await expect(dashboard.navigation).toBeVisible();
    await expect(dashboard.heading).toBeVisible();
    await expect(dashboard.lead(prospect)).toBeVisible();
  });
});
