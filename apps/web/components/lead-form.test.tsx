import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { AssessmentBanner } from "@/components/assessment-banner";
import { LeadForm } from "@/components/lead-form";
import {
  UploadError,
  uploadErrorMessage,
} from "@/lib/public-upload";

describe("public lead intake", () => {
  it("keeps the reviewer visibility warning explicit", () => {
    render(<AssessmentBanner />);
    expect(screen.getByText(/every Google-authenticated reviewer/i)).toBeVisible();
    expect(screen.getByText(/real PII and real CVs must not be used/i)).toBeVisible();
  });

  it("hides the resume file input without a full-width layout class", () => {
    render(<LeadForm uploader={vi.fn()} />);
    const resumeInput = screen.getByLabelText(/resume or CV/i);
    expect(resumeInput).toHaveAttribute("type", "file");
    expect(resumeInput).toHaveClass("sr-only");
    expect(resumeInput).not.toHaveClass("w-full");
  });

  it("reports accessible validation errors", async () => {
    const user = userEvent.setup();
    render(<LeadForm uploader={vi.fn()} />);

    await user.click(
      screen.getByRole("button", { name: /submit synthetic lead/i }),
    );

    expect(await screen.findByText("Enter a first name.")).toHaveAttribute(
      "role",
      "alert",
    );
    expect(screen.getByText("Enter a valid email address.")).toBeVisible();
    expect(screen.getByText("Choose one resume or CV.")).toBeVisible();
    expect(screen.getByText(/confirm that every field/i)).toBeVisible();
  });

  it("submits only the required normalized values and shows generic success", async () => {
    const user = userEvent.setup();
    const uploader = vi.fn().mockImplementation(async (_payload, progress) => {
      progress(100);
    });
    render(<LeadForm uploader={uploader} />);

    await user.type(screen.getByLabelText("First name"), " Ada ");
    await user.type(screen.getByLabelText("Last name"), " Lovelace ");
    await user.type(screen.getByLabelText("Email"), "ada@example.test");
    await user.upload(
      screen.getByLabelText(/resume or CV/i),
      new File(["synthetic"], "synthetic.pdf", { type: "application/pdf" }),
    );
    await user.click(screen.getByRole("checkbox"));
    await user.click(
      screen.getByRole("button", { name: /submit synthetic lead/i }),
    );

    await waitFor(() => expect(uploader).toHaveBeenCalledOnce());
    expect(uploader.mock.calls[0][0]).toEqual({
      firstName: "Ada",
      lastName: "Lovelace",
      email: "ada@example.test",
      resume: expect.any(File),
      syntheticDataAcknowledged: true,
    });
    expect(
      await screen.findByRole("heading", { name: "Submission received" }),
    ).toBeVisible();
  });

  it("includes optional comments when the submitter adds them", async () => {
    const user = userEvent.setup();
    const uploader = vi.fn().mockResolvedValue(undefined);
    render(<LeadForm uploader={uploader} />);

    await user.type(screen.getByLabelText("First name"), "Ada");
    await user.type(screen.getByLabelText("Last name"), "Lovelace");
    await user.type(screen.getByLabelText("Email"), "ada@example.test");
    await user.type(
      screen.getByRole("textbox", { name: /comments/i }),
      "Please review visa timing.",
    );
    await user.upload(
      screen.getByLabelText(/resume or CV/i),
      new File(["synthetic"], "synthetic.pdf", { type: "application/pdf" }),
    );
    await user.click(screen.getByRole("checkbox"));
    await user.click(
      screen.getByRole("button", { name: /submit synthetic lead/i }),
    );

    await waitFor(() => expect(uploader).toHaveBeenCalledOnce());
    expect(uploader.mock.calls[0][0]).toEqual({
      firstName: "Ada",
      lastName: "Lovelace",
      email: "ada@example.test",
      resume: expect.any(File),
      syntheticDataAcknowledged: true,
      comments: "Please review visa timing.",
    });
  });

  it("shows mapped API errors and returns the required status copy", async () => {
    const user = userEvent.setup();
    const uploader = vi
      .fn()
      .mockRejectedValue(new UploadError(429, uploadErrorMessage(429)));
    render(<LeadForm uploader={uploader} />);

    await user.type(screen.getByLabelText("First name"), "Test");
    await user.type(screen.getByLabelText("Last name"), "Person");
    await user.type(screen.getByLabelText("Email"), "test@example.test");
    await user.upload(
      screen.getByLabelText(/resume or CV/i),
      new File(["synthetic"], "synthetic.docx"),
    );
    await user.click(screen.getByRole("checkbox"));
    await user.click(
      screen.getByRole("button", { name: /submit synthetic lead/i }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Too many submissions",
    );
    expect(uploadErrorMessage(413)).toMatch(/10 MiB/);
    expect(uploadErrorMessage(422)).toMatch(/validate/);
    expect(uploadErrorMessage(503)).toMatch(/temporarily unavailable/);
  });
});
