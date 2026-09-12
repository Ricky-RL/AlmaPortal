import "server-only";

import {
  createHmac,
  randomBytes,
  timingSafeEqual,
} from "node:crypto";
import type { NextRequest, NextResponse } from "next/server";

function hosted() {
  return (
    process.env.NODE_ENV === "production" ||
    process.env.APP_URL?.startsWith("https://") === true
  );
}

export function csrfCookieName() {
  return hosted() ? "__Host-alma-csrf" : "alma-csrf";
}

function csrfSecret() {
  const value = process.env.CSRF_SECRET;
  if (!value || value.length < 32) {
    throw new Error("CSRF_SECRET must contain at least 32 characters.");
  }
  return value;
}

export function canonicalRequestError(request: NextRequest) {
  const configured = process.env.APP_URL;
  if (!configured) return "The canonical application URL is not configured.";

  let canonical: URL;
  try {
    canonical = new URL(configured);
  } catch {
    return "The canonical application URL is invalid.";
  }
  const localHttp =
    canonical.protocol === "http:" &&
    (canonical.hostname === "localhost" ||
      canonical.hostname === "127.0.0.1");
  if (
    (canonical.protocol !== "https:" && !localHttp) ||
    canonical.username ||
    canonical.password ||
    canonical.search ||
    canonical.hash
  ) {
    return "The canonical application URL is invalid.";
  }

  if (request.headers.get("origin") !== canonical.origin) {
    return "Request origin is not allowed.";
  }
  if (request.headers.get("host")?.toLowerCase() !== canonical.host.toLowerCase()) {
    return "Request host is not allowed.";
  }
  return null;
}

export function createCsrfToken(userId: string, nonce: string) {
  return createHmac("sha256", csrfSecret())
    .update(`${userId}:${nonce}`)
    .digest("base64url");
}

export function setCsrfCookie(response: NextResponse, nonce: string) {
  response.cookies.set(csrfCookieName(), nonce, {
    httpOnly: true,
    sameSite: "lax",
    secure: hosted(),
    path: "/",
    maxAge: 60 * 60 * 8,
  });
}

export function issueCsrf(response: NextResponse, request: NextRequest, userId: string) {
  const nonce =
    request.cookies.get(csrfCookieName())?.value ??
    randomBytes(32).toString("base64url");
  setCsrfCookie(response, nonce);
  return createCsrfToken(userId, nonce);
}

export function validCsrf(request: NextRequest, userId: string) {
  const nonce = request.cookies.get(csrfCookieName())?.value;
  const supplied = request.headers.get("x-csrf-token");
  if (!nonce || !supplied) return false;

  const expected = Buffer.from(createCsrfToken(userId, nonce));
  const actual = Buffer.from(supplied);
  return (
    expected.length === actual.length && timingSafeEqual(expected, actual)
  );
}
