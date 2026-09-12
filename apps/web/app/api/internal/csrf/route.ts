import { NextResponse, type NextRequest } from "next/server";
import { authenticatedAccessToken } from "@/lib/api/server";
import { issueCsrf } from "@/lib/security/csrf";

export const dynamic = "force-dynamic";
export const revalidate = 0;

function noStore(response: NextResponse) {
  response.headers.set("Cache-Control", "private, no-store");
  response.headers.set("Pragma", "no-cache");
  response.headers.set("Vary", "Cookie");
  return response;
}

export async function GET(request: NextRequest) {
  const auth = await authenticatedAccessToken();
  if (!auth) {
    return noStore(
      NextResponse.json({ detail: "Authentication required." }, { status: 401 }),
    );
  }

  const response = NextResponse.json({ token: "" });
  const token = issueCsrf(response, request, auth.user.id);
  const finalResponse = NextResponse.json({ token });
  response.cookies.getAll().forEach((cookie) => finalResponse.cookies.set(cookie));
  return noStore(finalResponse);
}
