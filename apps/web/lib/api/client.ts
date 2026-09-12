import {
  normalizeLeadDetail,
  normalizeSearchPage,
  normalizeSummary,
  normalizeTicket,
  type LeadStatus,
  type RetryRequest,
} from "@/lib/api/contracts";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function responseBody(response: Response) {
  const type = response.headers.get("content-type") ?? "";
  if (type.includes("json")) return response.json();
  const text = await response.text();
  return text ? { detail: text } : {};
}

function detail(value: unknown) {
  if (!value || typeof value !== "object") return undefined;
  const body = value as Record<string, unknown>;
  const message = body.detail ?? body.message ?? body.error;
  return typeof message === "string" ? message : undefined;
}

async function csrfToken() {
  const response = await fetch(
    new URL("/api/internal/csrf", window.location.origin),
    {
    credentials: "same-origin",
    cache: "no-store",
    },
  );
  const body = await responseBody(response);
  if (!response.ok) {
    throw new ApiError(response.status, "Your session could not be verified.");
  }
  return detail(body) ?? (body as { token?: string }).token ?? "";
}

async function internalRequest(path: string, init: RequestInit = {}) {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (method !== "GET" && method !== "HEAD") {
    if (init.body !== undefined) headers.set("Content-Type", "application/json");
    headers.set("X-CSRF-Token", await csrfToken());
  }

  const response = await fetch(
    new URL(`/api/internal/${path}`, window.location.origin),
    {
    ...init,
    method,
    headers,
    credentials: "same-origin",
    cache: "no-store",
    },
  );
  const body = await responseBody(response);
  if (!response.ok) {
    throw new ApiError(
      response.status,
      detail(body) ?? "The request could not be completed.",
    );
  }
  return body;
}

export async function getLeadSummary() {
  return normalizeSummary(await internalRequest("leads/summary"));
}

export async function searchLeads(input: {
  q: string;
  status: LeadStatus | "";
  cursor: string | null;
  limit?: number;
}) {
  return normalizeSearchPage(
    await internalRequest("leads/search", {
      method: "POST",
      body: JSON.stringify({
        q: input.q || null,
        status: input.status || null,
        cursor: input.cursor,
        limit: input.limit ?? 20,
      }),
    }),
  );
}

export async function getLead(id: string) {
  return normalizeLeadDetail(
    await internalRequest(`leads/${encodeURIComponent(id)}`),
  );
}

export async function reachOut(id: string) {
  await internalRequest(`leads/${encodeURIComponent(id)}/status`, {
    method: "PATCH",
    body: JSON.stringify({ status: "REACHED_OUT" }),
  });
  return getLead(id);
}

export async function requestResumeTicket(id: string) {
  return normalizeTicket(
    await internalRequest(`leads/${encodeURIComponent(id)}/resume-download`, {
      method: "POST",
    }),
  );
}

export async function retryDelivery(id: string, request: RetryRequest) {
  await internalRequest(
    `leads/${encodeURIComponent(id)}/deliveries/${encodeURIComponent(request.deliveryId)}/retry`,
    {
      method: "POST",
      body: JSON.stringify({
        duplicate_risk_confirmed: request.confirmDuplicateRisk,
      }),
    },
  );
  return getLead(id);
}
