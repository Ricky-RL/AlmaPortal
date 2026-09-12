"use client";

import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { Button } from "@/components/ui";
import { safeNextPath } from "@/lib/safe-redirect";
import { createSupabaseBrowserClient } from "@/lib/supabase/browser";

export function GoogleLogin() {
  const searchParams = useSearchParams();
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const displayedError = error
    ? error
    : searchParams.has("error")
      ? "Google sign-in could not be completed. Please try again."
      : undefined;

  async function signIn() {
    setBusy(true);
    setError(undefined);
    try {
      const callback = new URL("/auth/callback", window.location.origin);
      callback.searchParams.set("next", safeNextPath(searchParams.get("next")));
      const supabase = createSupabaseBrowserClient();
      const { error: authError } = await supabase.auth.signInWithOAuth({
        provider: "google",
        options: { redirectTo: callback.toString() },
      });
      if (authError) throw authError;
    } catch {
      setError("Google sign-in could not be started. Please try again.");
      setBusy(false);
    }
  }

  return (
    <div>
      <Button type="button" className="w-full" onClick={signIn} disabled={busy}>
        {busy ? "Opening Google…" : "Continue with Google"}
      </Button>
      {displayedError && (
        <p className="mt-4 text-sm font-medium text-red-800" role="alert">
          {displayedError}
        </p>
      )}
    </div>
  );
}
