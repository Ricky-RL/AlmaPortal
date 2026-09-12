import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

function noStore(response: NextResponse) {
  response.headers.set("Cache-Control", "private, no-store");
  response.headers.set("Pragma", "no-cache");
  response.headers.set("Vary", "Cookie");
  return response;
}

export async function proxy(request: NextRequest) {
  let response = NextResponse.next({ request });
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

  if (!url || !anonKey) {
    if (request.nextUrl.pathname.startsWith("/leads")) {
      return noStore(NextResponse.redirect(new URL("/login", request.url)));
    }
    return noStore(response);
  }

  const supabase = createServerClient(url, anonKey, {
    cookies: {
      getAll: () => request.cookies.getAll(),
      setAll: (values) => {
        values.forEach(({ name, value }) => request.cookies.set(name, value));
        response = NextResponse.next({ request });
        values.forEach(({ name, value, options }) =>
          response.cookies.set(name, value, {
            ...options,
            secure:
              process.env.NODE_ENV === "production" ||
              process.env.APP_URL?.startsWith("https://")
                ? true
                : options.secure,
            sameSite: "lax",
          }),
        );
      },
    },
  });

  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user && request.nextUrl.pathname.startsWith("/leads")) {
    const login = new URL("/login", request.url);
    login.searchParams.set("next", request.nextUrl.pathname);
    const redirect = NextResponse.redirect(login);
    response.cookies
      .getAll()
      .forEach((cookie) => redirect.cookies.set(cookie));
    return noStore(redirect);
  }

  return noStore(response);
}

export const config = {
  matcher: ["/leads/:path*", "/login", "/auth/callback", "/api/internal/:path*"],
};
