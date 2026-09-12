import type { Metadata } from "next";
import { LeadDetail } from "@/components/lead-detail";

export const metadata: Metadata = { title: "Lead details" };
export const dynamic = "force-dynamic";
export const revalidate = 0;

export default async function LeadDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <LeadDetail id={id} />;
}
