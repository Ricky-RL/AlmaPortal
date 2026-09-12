import Link from "next/link";
import { ReviewerAccountMenu } from "@/components/reviewer-account-menu";

export function ReviewerNav({ email }: { email?: string | null }) {
  return (
    <nav
      aria-label="Reviewer navigation"
      className="border-b border-[var(--line)] bg-[var(--paper)]"
    >
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-5 py-3 sm:px-8">
        <Link
          href="/leads"
          className="font-semibold text-[var(--green)] underline-offset-4 hover:underline"
        >
          Lead review
        </Link>
        <ReviewerAccountMenu email={email} />
      </div>
    </nav>
  );
}
