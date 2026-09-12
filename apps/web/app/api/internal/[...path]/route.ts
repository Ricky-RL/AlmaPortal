import { NextResponse, type NextRequest } from "next/server";
import { z } from "zod";
import {
  authenticatedAccessToken,
  fetchProtectedApi,
} from "@/lib/api/server";
import {
  canonicalRequestError,
  validCsrf,
} from "@/lib/security/csrf";

export const dynamic = "force-dynamic";
export const revalidate = 0;

const searchSchema = z
  .object({
    q: z.string().trim().max(200).nullable(),
    status: z.enum(["PENDING", "REACHED_OUT"]).nullable(),
    cursor: z.string().max(1024).nullable(),
    limit: z.number().int().min(1).max(100),
  })
  .strict();

const statusSchema = z
  .object({ status: z.literal("REACHED_OUT") })
  .strict();

const retrySchema = z
  .object({
    duplicate_risk_confirmed: z.boolean(),
  })
  .strict();

type RouteContext = { params: Promise<{ path: string[] }> };

function noStore(response: NextResponse) {
  response.headers.set("Cache-Control", "private, no-store");
  response.headers.set("Pragma", "no-cache");
  response.headers.set("Vary", "Cookie");
  response.headers.set("X-Content-Type-Options", "nosniff");
  return response;
}

function jsonError(status: number, detail: string) {
  return noStore(NextResponse.json({ detail }, { status }));
}

function upstreamPath(method: string, segments: string[]) {
  if (method === "GET" && segments.join("/") === "me") return "/api/v1/me";
  if (method === "GET" && segments.join("/") === "leads/summary") {
    return "/api/v1/leads/summary";
  }
  if (segments[0] !== "leads" || !segments[1]) return null;
  const id = encodeURIComponent(segments[1]);
  if (method === "GET" && segments.length === 2) return `/api/v1/leads/${id}`;
  if (method === "POST" && segments.join("/") === "leads/search") {
    return "/api/v1/leads/search";
  }
  if (method === "PATCH" && segments[2] === "status" && segments.length === 3) {
    return `/api/v1/leads/${id}/status`;
  }
  if (
    method === "POST" &&
    segments[2] === "resume-download" &&
    segments.length === 3
  ) {
    return `/api/v1/leads/${id}/resume-download`;
  }
  if (
    method === "POST" &&
    segments[2] === "deliveries" &&
    segments[3] &&
    segments[4] === "retry" &&
    segments.length === 5
  ) {
    return `/api/v1/leads/${id}/deliveries/${encodeURIComponent(segments[3])}/retry`;
  }
  return null;
}

async function validatedBody(method: string, segments: string[], request: NextRequest) {
  if (method === "GET") return { ok: true as const, body: undefined };
  if (method === "POST" && segments[2] === "resume-download") {
    return (await request.text()).length === 0
      ? { ok: true as const, body: undefined }
      : { ok: false as const };
  }

  let input: unknown;
  try {
    input = await request.json();
  } catch {
    return { ok: false as const };
  }

  let result: z.ZodSafeParseResult<unknown>;
  if (method === "POST" && segments.join("/") === "leads/search") {
    result = searchSchema.safeParse(input);
  } else if (method === "PATCH" && segments[2] === "status") {
    result = statusSchema.safeParse(input);
  } else if (
    method === "POST" &&
    segments[2] === "deliveries" &&
    segments[4] === "retry"
  ) {
    result = retrySchema.safeParse(input);
  } else {
    return { ok: false as const };
  }

  return result.success
    ? { ok: true as const, body: JSON.stringify(result.data) }
    : { ok: false as const };
}

async function handle(request: NextRequest, context: RouteContext) {
  const { path: segments } = await context.params;
  const method = request.method.toUpperCase();
  const path = upstreamPath(method, segments);
  if (!path) return jsonError(404, "Internal route not found.");

  const auth = await authenticatedAccessToken();
  if (!auth) return jsonError(401, "Authentication required.");

  if (method !== "GET" && method !== "HEAD") {
    const originError = canonicalRequestError(request);
    if (originError) return jsonError(403, originError);
    if (!validCsrf(request, auth.user.id)) {
      return jsonError(403, "CSRF validation failed.");
    }
  }

  const body = await validatedBody(method, segments, request);
  if (!body.ok) return jsonError(422, "Request body is invalid.");

  let upstream: Response;
  try {
    upstream = await fetchProtectedApi(path, auth.token, {
      method,
      body: body.body,
    });
  } catch {
    return jsonError(503, "The lead service is unavailable.");
  }

  const response = new NextResponse(await upstream.arrayBuffer(), {
    status: upstream.status,
    headers: {
      "Content-Type":
        upstream.headers.get("content-type") ?? "application/json",
    },
  });
  return noStore(response);
}

export const GET = handle;
export const POST = handle;
export const PATCH = handle;
