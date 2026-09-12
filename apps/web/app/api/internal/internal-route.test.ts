import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { fetchProtectedApi } = vi.hoisted(() => ({
  fetchProtectedApi: vi.fn(),
}));

vi.mock("@/lib/api/server", () => ({
  authenticatedAccessToken: vi.fn().mockResolvedValue({
    token: "access-token",
    user: { id: "reviewer-1", email: "reviewer@example.test" },
  }),
  fetchProtectedApi,
}));

import {
  GET,
  PATCH,
  POST,
} from "@/app/api/internal/[...path]/route";
import { GET as GET_CSRF } from "@/app/api/internal/csrf/route";
import { createCsrfToken } from "@/lib/security/csrf";

describe("internal route security", () => {
  beforeEach(() => {
    process.env.APP_URL = "https://portal.example.test";
    process.env.CSRF_SECRET = "a-secure-test-secret-that-is-at-least-32-characters";
    fetchProtectedApi.mockReset();
    fetchProtectedApi.mockImplementation(async () => Response.json({}));
  });

  it("rejects a mutating request from a different origin", async () => {
    const request = new NextRequest(
      "https://portal.example.test/api/internal/leads/lead-1/status",
      {
        method: "PATCH",
        headers: {
          host: "portal.example.test",
          origin: "https://attacker.example.test",
          "content-type": "application/json",
        },
        body: JSON.stringify({ status: "REACHED_OUT" }),
      },
    );

    const response = await PATCH(request, {
      params: Promise.resolve({ path: ["leads", "lead-1", "status"] }),
    });

    expect(response.status).toBe(403);
    expect(await response.json()).toEqual({
      detail: "Request origin is not allowed.",
    });
    expect(response.headers.get("cache-control")).toBe("private, no-store");
    expect(fetchProtectedApi).not.toHaveBeenCalled();
  });

  it("rejects a same-origin mutation without the session CSRF token", async () => {
    const request = new NextRequest(
      "https://portal.example.test/api/internal/leads/lead-1/status",
      {
        method: "PATCH",
        headers: {
          host: "portal.example.test",
          origin: "https://portal.example.test",
          "content-type": "application/json",
        },
        body: JSON.stringify({ status: "REACHED_OUT" }),
      },
    );

    const response = await PATCH(request, {
      params: Promise.resolve({ path: ["leads", "lead-1", "status"] }),
    });

    expect(response.status).toBe(403);
    expect(await response.json()).toEqual({
      detail: "CSRF validation failed.",
    });
  });

  it("issues a user-bound CSRF token in a secure no-store response", async () => {
    const response = await GET_CSRF(
      new NextRequest("https://portal.example.test/api/internal/csrf", {
        headers: { host: "portal.example.test" },
      }),
    );

    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("private, no-store");
    expect((await response.json()).token).toMatch(/^[A-Za-z0-9_-]{43}$/);
    const cookie = response.cookies.get("__Host-alma-csrf");
    expect(cookie).toMatchObject({
      httpOnly: true,
      sameSite: "lax",
      secure: true,
      path: "/",
    });
  });

  it("forwards authenticated reads without caching their response", async () => {
    fetchProtectedApi.mockResolvedValueOnce(
      Response.json({ email: "reviewer@example.test" }),
    );
    const request = new NextRequest(
      "https://portal.example.test/api/internal/me",
      { headers: { host: "portal.example.test" } },
    );

    const response = await GET(request, {
      params: Promise.resolve({ path: ["me"] }),
    });

    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("private, no-store");
    expect(fetchProtectedApi).toHaveBeenCalledWith(
      "/api/v1/me",
      "access-token",
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("maps every lead route and body to the FastAPI contract", async () => {
    const nonce = "csrf-session-nonce";
    const token = createCsrfToken("reviewer-1", nonce);
    const mutation = (
      path: string,
      method: "POST" | "PATCH",
      body?: unknown,
    ) =>
      new NextRequest(`https://portal.example.test/api/internal/${path}`, {
        method,
        headers: {
          host: "portal.example.test",
          origin: "https://portal.example.test",
          cookie: `__Host-alma-csrf=${nonce}`,
          "x-csrf-token": token,
          ...(body === undefined ? {} : { "content-type": "application/json" }),
        },
        body: body === undefined ? undefined : JSON.stringify(body),
      });

    await GET(
      new NextRequest(
        "https://portal.example.test/api/internal/leads/summary",
        { headers: { host: "portal.example.test" } },
      ),
      { params: Promise.resolve({ path: ["leads", "summary"] }) },
    );
    await GET(
      new NextRequest(
        "https://portal.example.test/api/internal/leads/lead-1",
        { headers: { host: "portal.example.test" } },
      ),
      { params: Promise.resolve({ path: ["leads", "lead-1"] }) },
    );
    await POST(
      mutation("leads/search", "POST", {
        q: "ada",
        status: "PENDING",
        cursor: null,
        limit: 20,
      }),
      { params: Promise.resolve({ path: ["leads", "search"] }) },
    );
    await PATCH(
      mutation("leads/lead-1/status", "PATCH", {
        status: "REACHED_OUT",
      }),
      { params: Promise.resolve({ path: ["leads", "lead-1", "status"] }) },
    );
    await POST(
      mutation("leads/lead-1/resume-download", "POST"),
      {
        params: Promise.resolve({
          path: ["leads", "lead-1", "resume-download"],
        }),
      },
    );
    await POST(
      mutation(
        "leads/lead-1/deliveries/delivery-1/retry",
        "POST",
        { duplicate_risk_confirmed: true },
      ),
      {
        params: Promise.resolve({
          path: [
            "leads",
            "lead-1",
            "deliveries",
            "delivery-1",
            "retry",
          ],
        }),
      },
    );

    expect(fetchProtectedApi.mock.calls).toEqual([
      ["/api/v1/leads/summary", "access-token", { method: "GET", body: undefined }],
      ["/api/v1/leads/lead-1", "access-token", { method: "GET", body: undefined }],
      [
        "/api/v1/leads/search",
        "access-token",
        {
          method: "POST",
          body: JSON.stringify({
            q: "ada",
            status: "PENDING",
            cursor: null,
            limit: 20,
          }),
        },
      ],
      [
        "/api/v1/leads/lead-1/status",
        "access-token",
        {
          method: "PATCH",
          body: JSON.stringify({ status: "REACHED_OUT" }),
        },
      ],
      [
        "/api/v1/leads/lead-1/resume-download",
        "access-token",
        { method: "POST", body: undefined },
      ],
      [
        "/api/v1/leads/lead-1/deliveries/delivery-1/retry",
        "access-token",
        {
          method: "POST",
          body: JSON.stringify({ duplicate_risk_confirmed: true }),
        },
      ],
    ]);
  });
});
