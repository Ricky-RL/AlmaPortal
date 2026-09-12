import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";

function supabaseConfig() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !anonKey) {
    throw new Error("Supabase authentication is not configured.");
  }
  return { url, anonKey };
}

export async function createSupabaseServerClient() {
  const cookieStore = await cookies();
  const { url, anonKey } = supabaseConfig();

  return createServerClient(url, anonKey, {
    cookies: {
      getAll: () => cookieStore.getAll(),
      setAll: (values) => {
        try {
          values.forEach(({ name, value, options }) =>
            cookieStore.set(name, value, {
              ...options,
              secure:
                process.env.NODE_ENV === "production" ||
                process.env.APP_URL?.startsWith("https://")
                  ? true
                  : options.secure,
              sameSite: "lax",
            }),
          );
        } catch {
          // Server Components cannot write cookies. proxy.ts performs refreshes.
        }
      },
    },
  });
}
