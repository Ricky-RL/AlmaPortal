import { describe, expect, it } from "vitest";
import { safeNextPath } from "@/lib/safe-redirect";

describe("authentication redirects", () => {
  it("accepts local paths and rejects external or protocol-relative targets", () => {
    expect(safeNextPath("/leads/example")).toBe("/leads/example");
    expect(safeNextPath("https://attacker.test")).toBe("/leads");
    expect(safeNextPath("//attacker.test/path")).toBe("/leads");
    expect(safeNextPath("/\\attacker.test/path")).toBe("/leads");
    expect(safeNextPath(null)).toBe("/leads");
  });
});
