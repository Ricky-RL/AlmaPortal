import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchProtectedApi } from "@/lib/api/server";

describe("protected API forwarding", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("forwards the refreshed bearer token with no-store caching", async () => {
    process.env.API_URL = "https://api.example.test";
    const fetchMock = vi.fn().mockResolvedValue(Response.json({ ok: true }));
    vi.stubGlobal("fetch", fetchMock);

    await fetchProtectedApi("/api/v1/leads/summary", "refreshed-token");

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = new Headers(init.headers);
    expect(url).toBe("https://api.example.test/api/v1/leads/summary");
    expect(init.cache).toBe("no-store");
    expect(headers.get("authorization")).toBe("Bearer refreshed-token");
    expect(headers.has("content-type")).toBe(false);
  });
});
