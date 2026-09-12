import { ReviewerNav } from "@/components/reviewer-nav";
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
      <ReviewerNav email={reviewer.email} />
      {children}
    </>
  );
}
