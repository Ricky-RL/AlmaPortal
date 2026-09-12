import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { SignOutButton } from "@/components/sign-out-button";
import { ReviewerNav } from "@/components/reviewer-nav";

vi.mock("@/lib/auth-actions", () => ({
  signOutReviewer: vi.fn(async () => undefined),
}));

import { signOutReviewer } from "@/lib/auth-actions";

describe("reviewer sign out", () => {
  it("exposes an accessible sign out control in reviewer navigation", () => {
    render(<ReviewerNav email="lawyer@example.test" />);

    expect(
      screen.getByRole("navigation", { name: "Reviewer navigation" }),
    ).toBeVisible();
    expect(screen.getByText("lawyer@example.test")).toBeVisible();
    expect(screen.getByRole("button", { name: "Sign out" })).toBeVisible();
  });

  it("submits the sign out action", async () => {
    const user = userEvent.setup();
    render(<SignOutButton />);

    await user.click(screen.getByRole("button", { name: "Sign out" }));

    expect(signOutReviewer).toHaveBeenCalled();
  });
});
