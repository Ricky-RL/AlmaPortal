import { contract } from "../helpers/contract.js";
import { invalidTextFile, oversizedPdf } from "../fixtures/tiny-pdf.js";
import { expect, test } from "../fixtures/test.js";

test.describe("public prospect submission", () => {
  test("submits a synthetic prospect and shows success", async ({
    data,
    publicForm,
    resend,
  }) => {
    const prospect = data.prospect("public success");

    await publicForm.open();
    await expect(publicForm.main).toBeVisible();
    await expect(
      publicForm.page.getByRole("heading", { level: 1 }),
    ).toBeVisible();
    await expect(publicForm.form).toBeVisible();
    await expect(publicForm.comments).toBeVisible();

    await publicForm.fill(prospect);
    await publicForm.submitForm();

    await expect
      .poll(() => publicForm.submissionSucceeded())
      .toBe(true);

    await expect
      .poll(async () => (await resend.messages()).length)
      .toBeGreaterThan(0);
  });

  test("requires the acknowledgement before submission", async ({
    data,
    publicForm,
  }) => {
    const prospect = data.prospect("acknowledgement required");
    let submissionRequests = 0;
    publicForm.page.on("request", (request) => {
      if (
        request.method() === "POST" &&
        new URL(request.url()).pathname === contract.paths.submissionApi
      ) {
        submissionRequests += 1;
      }
    });

    await publicForm.open();
    await publicForm.fill(prospect, { acknowledge: false });
    const submitDisabled = await publicForm.submit.isDisabled();
    if (!submitDisabled) {
      await publicForm.submitForm();
    }

    await expect
      .poll(async () => {
        const nativeMissing = await publicForm.acknowledgement.evaluate(
          (element) =>
            element instanceof HTMLInputElement &&
            element.validity.valueMissing,
        );
        const visibleError = await publicForm
          .validationMessage(/acknowledge|consent|confirm|agree|required/i)
          .isVisible();
        return submitDisabled || nativeMissing || visibleError;
      })
      .toBe(true);
    expect(submissionRequests).toBe(0);
  });

  test("rejects an unsupported CV file type", async ({ data, publicForm }) => {
    const prospect = data.prospect("invalid file");

    await publicForm.open();
    await publicForm.fill(prospect, { file: invalidTextFile });
    await publicForm.submitForm();

    await expect(
      publicForm.validationMessage(/pdf|file type|invalid file/i),
    ).toBeVisible();
  });

  test("rejects an oversized CV in the browser without submitting", async ({
    data,
    publicForm,
  }) => {
    const prospect = data.prospect("oversized file");
    let submissionRequests = 0;
    publicForm.page.on("request", (request) => {
      if (
        request.method() === "POST" &&
        new URL(request.url()).pathname === contract.paths.submissionApi
      ) {
        submissionRequests += 1;
      }
    });

    await publicForm.open();
    await publicForm.fill(prospect, {
      file: oversizedPdf(contract.data.maxUploadBytes),
    });
    await publicForm.submitForm();

    await expect(
      publicForm.validationMessage(/no larger than 10 MiB|too large|file size/i),
    ).toBeVisible();
    expect(submissionRequests).toBe(0);
  });
});
