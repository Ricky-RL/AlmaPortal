import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { LeadDetail } from "@/components/lead-detail";
import {
  deliveryStateLabel,
  hasDuplicateRetryRisk,
} from "@/components/delivery-state";
import { server } from "@/test/msw/server";

function lead(status = "PENDING", prospectState = "unknown") {
  return {
    id: "lead-1",
    first_name: "Ada",
    last_name: "Lovelace",
    email: "ada@example.test",
    status,
    resume_filename: "synthetic.pdf",
    created_at: "2026-09-10T12:00:00Z",
    updated_at: "2026-09-11T12:00:00Z",
    deliveries: [
      {
        id: "delivery-prospect",
        kind: "prospect",
        state: prospectState,
        provider_accepted: prospectState === "provider_accepted",
        attempts: [
          {
            id: "attempt-1",
            attempt_number: 2,
            state: prospectState,
            outcome: prospectState,
            trigger: "manual",
            reviewer: {
              id: "reviewer-1",
              email: "reviewer@example.test",
            },
            attempted_at: "2026-09-10T12:01:00Z",
            started_at: "2026-09-10T12:01:00Z",
            ended_at: "2026-09-10T12:01:10Z",
            sanitized_error: "Outcome is unknown.",
          },
        ],
      },
      {
        id: "delivery-attorney",
        kind: "attorney",
        state: "provider_accepted",
        provider_accepted: true,
        attempts: [],
      },
    ],
  };
}

describe("lead details", () => {
  beforeEach(() => {
    process.env.NEXT_PUBLIC_API_URL = "https://alma-api.example.test";
  });

  it("confirms status, gets a download ticket, and confirms risky retries", async () => {
    const retryBodies: unknown[] = [];
    const navigate = vi.fn();
    let status = "PENDING";
    server.use(
      http.get("*/api/internal/csrf", () =>
        HttpResponse.json({ token: "csrf-token" }),
      ),
      http.get("*/api/internal/leads/lead-1", () =>
        HttpResponse.json(lead(status)),
      ),
      http.patch("*/api/internal/leads/lead-1/status", async ({ request }) => {
        expect(request.headers.get("x-csrf-token")).toBe("csrf-token");
        expect(await request.json()).toEqual({ status: "REACHED_OUT" });
        status = "REACHED_OUT";
        return HttpResponse.json(lead(status));
      }),
      http.post(
        "*/api/internal/leads/lead-1/resume-download",
        () =>
          HttpResponse.json({
            url: "https://alma-api.example.test/api/v1/downloads/resume?ticket=synthetic",
            expires_in_seconds: 60,
          }),
      ),
      http.post(
        "*/api/internal/leads/lead-1/deliveries/delivery-prospect/retry",
        async ({ request }) => {
        retryBodies.push(await request.json());
        return HttpResponse.json({
          id: "delivery-prospect",
          kind: "prospect",
          state: "pending",
        });
        },
      ),
    );

    const user = userEvent.setup();
    render(<LeadDetail id="lead-1" navigate={navigate} />);
    expect(
      await screen.findByRole("heading", { name: "Ada Lovelace" }),
    ).toBeVisible();
    expect(screen.getByText("None provided")).toBeVisible();
    expect(screen.getByText(/does not prove.*recipient's inbox/i)).toBeVisible();
    expect(screen.getByText(/manual retry by reviewer@example.test/i)).toBeVisible();

    await user.click(screen.getByRole("button", { name: "Mark reached out" }));
    expect(screen.getByRole("alertdialog")).toBeVisible();
    await user.click(
      screen.getByRole("button", { name: "Confirm reached out" }),
    );
    await waitFor(() =>
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument(),
    );
    expect(screen.getByText("Reached out")).toBeVisible();

    await user.click(screen.getByRole("button", { name: "Download CV" }));
    await waitFor(() =>
      expect(navigate).toHaveBeenCalledWith(
        "https://alma-api.example.test/api/v1/downloads/resume?ticket=synthetic",
      ),
    );

    const retry = screen.getByRole("button", { name: "Retry notification" });
    expect(retry).toBeDisabled();
    await user.click(
      screen.getByRole("checkbox", { name: /retrying may send a duplicate/i }),
    );
    expect(retry).toBeEnabled();
    await user.click(retry);
    await waitFor(() =>
      expect(retryBodies).toContainEqual({
        duplicate_risk_confirmed: true,
      }),
    );
  });

  it("uses clear delivery labels and only flags uncertain outcomes", () => {
    expect(deliveryStateLabel("provider_accepted")).toBe("Provider accepted");
    expect(deliveryStateLabel("processing")).toBe("Processing");
    expect(hasDuplicateRetryRisk("unknown")).toBe(true);
    expect(hasDuplicateRetryRisk("failed")).toBe(false);
  });
});
