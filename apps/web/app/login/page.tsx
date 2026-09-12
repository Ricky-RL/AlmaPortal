import type { Metadata } from "next";
import { Suspense } from "react";
import { GoogleLogin } from "@/components/google-login";
import { Card } from "@/components/ui";

export const metadata: Metadata = { title: "Reviewer sign in" };

export default function LoginPage() {
  return (
    <main className="mx-auto flex min-h-[calc(100vh-66px)] max-w-md items-center px-5 py-12">
      <Card className="w-full">
        <p className="text-sm font-bold uppercase tracking-[0.14em] text-[var(--green-light)]">
          Reviewer access
        </p>
        <h1 className="mt-3 text-3xl font-bold tracking-tight">Sign in</h1>
        <p className="mb-7 mt-3 leading-7 text-[var(--muted)]">
          Use Google to review synthetic assessment leads. All authenticated
          reviewers can view every submission.
        </p>
        <Suspense fallback={<p>Preparing sign-in…</p>}>
          <GoogleLogin />
        </Suspense>
      </Card>
    </main>
  );
}
