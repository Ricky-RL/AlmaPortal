import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ReviewerNav } from "@/components/reviewer-nav";

vi.mock("@/lib/auth-actions", () => ({
  signOutReviewer: vi.fn(async () => undefined),
}));

import { signOutReviewer } from "@/lib/auth-actions";

describe("reviewer account menu", () => {
  it("keeps sign out inside an email dropdown", async () => {
    const user = userEvent.setup();
    render(<ReviewerNav email="lawyer@example.test" />);

    expect(
      screen.getByRole("navigation", { name: "Reviewer navigation" }),
    ).toBeVisible();
    const account = screen.getByRole("button", { name: "lawyer@example.test" });
    expect(account).toHaveAttribute("aria-expanded", "false");
    expect(
      screen.queryByRole("menuitem", { name: "Sign out" }),
    ).not.toBeInTheDocument();

    await user.click(account);

    expect(account).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("menu", { name: "Account" })).toBeVisible();
    expect(screen.getByRole("menuitem", { name: "Sign out" })).toBeVisible();
  });

  it("submits the sign out action from the open menu", async () => {
    const user = userEvent.setup();
    render(<ReviewerNav email="lawyer@example.test" />);

    await user.click(
      screen.getByRole("button", { name: "lawyer@example.test" }),
    );
    await user.click(screen.getByRole("menuitem", { name: "Sign out" }));

    expect(signOutReviewer).toHaveBeenCalled();
  });

  it("closes the menu on escape", async () => {
    const user = userEvent.setup();
    render(<ReviewerNav email="lawyer@example.test" />);

    const account = screen.getByRole("button", { name: "lawyer@example.test" });
    await user.click(account);
    await user.keyboard("{Escape}");

    expect(account).toHaveAttribute("aria-expanded", "false");
    expect(
      screen.queryByRole("menuitem", { name: "Sign out" }),
    ).not.toBeInTheDocument();
  });
});
