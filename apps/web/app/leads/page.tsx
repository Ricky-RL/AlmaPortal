import type { Metadata } from "next";
import { LeadList } from "@/components/lead-list";

export const metadata: Metadata = { title: "Lead review" };
export const dynamic = "force-dynamic";
export const revalidate = 0;

export default function LeadsPage() {
  return (
    <main className="mx-auto max-w-6xl px-5 py-10 sm:px-8">
      <h1 className="text-3xl font-bold tracking-tight">Lead review</h1>
      <p className="mb-8 mt-2 max-w-2xl text-[var(--muted)]">
        Search all submitted lead fields, review delivery history, and record
        outreach.
      </p>
      <LeadList />
    </main>
  );
}
