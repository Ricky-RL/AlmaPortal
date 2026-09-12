import "server-only";

import { createSupabaseServerClient } from "@/lib/supabase/server";

export function protectedApiUrl(path: string) {
  const raw = process.env.API_URL;
  if (!raw) throw new Error("The protected API is not configured.");
  const url = new URL(raw);
  const localHttp =
    url.protocol === "http:" &&
    (url.hostname === "localhost" || url.hostname === "127.0.0.1");
  if (url.protocol !== "https:" && !localHttp) {
    throw new Error("The protected API URL must use HTTPS.");
  }
  if (url.username || url.password || url.search || url.hash) {
    throw new Error("The protected API URL is invalid.");
  }
  return `${url.origin}${url.pathname.replace(/\/+$/, "")}${path}`;
}

export async function authenticatedAccessToken() {
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return null;

  const {
    data: { session },
  } = await supabase.auth.getSession();
  return session?.access_token ? { token: session.access_token, user } : null;
}

export async function fetchProtectedApi(
  path: string,
  token: string,
  init: RequestInit = {},
) {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  headers.set("Authorization", `Bearer ${token}`);
  if (init.body) headers.set("Content-Type", "application/json");

  return fetch(protectedApiUrl(path), {
    ...init,
    headers,
    cache: "no-store",
  });
}
