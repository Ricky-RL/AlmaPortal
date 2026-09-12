"use client";

import { useActionState } from "react";
import { Button } from "@/components/ui";
import { signOutReviewer } from "@/lib/auth-actions";

export function SignOutButton() {
  const [error, action, pending] = useActionState(signOutReviewer, undefined);

  return (
    <div className="flex shrink-0 flex-col items-end">
      <form action={action}>
        <Button
          type="submit"
          variant="secondary"
          className="px-4"
          disabled={pending}
        >
          {pending ? "Signing out…" : "Sign out"}
        </Button>
      </form>
      {error ? (
        <p className="mt-1 max-w-44 text-right text-xs font-medium text-red-800" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
