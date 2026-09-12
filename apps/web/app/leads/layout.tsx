import Link from "next/link";
import { requireReviewer } from "@/lib/auth";

export const dynamic = "force-dynamic";
export const revalidate = 0;

export default async function LeadsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const reviewer = await requireReviewer();

  return (
    <>
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
          <span className="truncate text-sm text-[var(--muted)]">
            {reviewer.email}
          </span>
        </div>
      </nav>
      {children}
    </>
  );
}
