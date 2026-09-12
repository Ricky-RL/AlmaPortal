import { describe, expect, it } from "vitest";
import { validatedDownloadTicketUrl } from "@/lib/api/ticket";

describe("resume download ticket validation", () => {
  it("accepts an absolute ticket URL on the configured API origin", () => {
    expect(
      validatedDownloadTicketUrl(
        "https://api.example.test/api/v1/downloads/resume?ticket=synthetic",
        "https://api.example.test",
      ),
    ).toBe(
      "https://api.example.test/api/v1/downloads/resume?ticket=synthetic",
    );
  });

  it("rejects relative and cross-origin ticket URLs", () => {
    expect(() =>
      validatedDownloadTicketUrl(
        "/api/v1/downloads/resume?ticket=synthetic",
        "https://api.example.test",
      ),
    ).toThrow();
    expect(() =>
      validatedDownloadTicketUrl(
        "https://attacker.example.test/download?ticket=synthetic",
        "https://api.example.test",
      ),
    ).toThrow(/origin is not allowed/);
  });
});
