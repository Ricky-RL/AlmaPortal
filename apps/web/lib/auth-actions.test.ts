import { beforeEach, describe, expect, it, vi } from "vitest";

const signOut = vi.fn();

vi.mock("@/lib/supabase/server", () => ({
  createSupabaseServerClient: vi.fn(async () => ({
    auth: { signOut },
  })),
}));

vi.mock("next/navigation", () => ({
  redirect: vi.fn((path: string) => {
    throw new Error(`NEXT_REDIRECT:${path}`);
  }),
}));

import { redirect } from "next/navigation";
import { signOutReviewer } from "@/lib/auth-actions";

describe("signOutReviewer", () => {
  beforeEach(() => {
    signOut.mockReset();
    vi.mocked(redirect).mockClear();
  });

  it("clears the local session and sends the reviewer to sign in", async () => {
    signOut.mockResolvedValue({ error: null });

    await expect(signOutReviewer()).rejects.toThrow("NEXT_REDIRECT:/login");

    expect(signOut).toHaveBeenCalledWith({ scope: "local" });
    expect(redirect).toHaveBeenCalledWith("/login");
  });

  it("returns a readable error when the session cannot be cleared", async () => {
    signOut.mockResolvedValue({ error: { message: "provider unavailable" } });

    await expect(signOutReviewer()).resolves.toBe(
      "Sign out could not be completed. Please try again.",
    );
    expect(redirect).not.toHaveBeenCalled();
  });
});
