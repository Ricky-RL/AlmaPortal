import { NextResponse, type NextRequest } from "next/server";
import { safeNextPath } from "@/lib/safe-redirect";
import { createSupabaseServerClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

function noStore(response: NextResponse) {
  response.headers.set("Cache-Control", "private, no-store");
  response.headers.set("Pragma", "no-cache");
  response.headers.set("Vary", "Cookie");
  return response;
}

export async function GET(request: NextRequest) {
  const code = request.nextUrl.searchParams.get("code");
  const next = safeNextPath(request.nextUrl.searchParams.get("next"));
  const destination = new URL(next, request.nextUrl.origin);

  if (!code) {
    const login = new URL("/login", request.nextUrl.origin);
    login.searchParams.set("error", "missing_code");
    return noStore(NextResponse.redirect(login));
  }

  const supabase = await createSupabaseServerClient();
  const { error } = await supabase.auth.exchangeCodeForSession(code);
  if (error) {
    const login = new URL("/login", request.nextUrl.origin);
    login.searchParams.set("error", "callback_failed");
    return noStore(NextResponse.redirect(login));
  }

  return noStore(NextResponse.redirect(destination));
}
