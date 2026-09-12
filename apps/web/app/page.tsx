import Image from "next/image";
import Link from "next/link";
import { AssessmentBanner } from "@/components/assessment-banner";
import { LeadForm } from "@/components/lead-form";

export default function HomePage() {
  return (
    <>
      <AssessmentBanner />
      <main className="mx-auto grid max-w-6xl gap-12 px-5 py-12 sm:px-8 lg:grid-cols-[0.8fr_1.2fr] lg:py-20">
        <section className="self-center">
          <Image
            src="/alma-logo.png"
            alt="Alma"
            width={214}
            height={96}
            priority
            className="mb-8 h-auto w-[214px] max-w-[70%] mix-blend-multiply"
          />
          <p className="mb-4 text-sm font-bold uppercase tracking-[0.16em] text-[var(--green-light)]">
            Legal lead assessment
          </p>
          <h1 className="max-w-xl text-4xl font-bold leading-tight tracking-tight sm:text-5xl">
            Share a synthetic prospect profile for review.
          </h1>
          <p className="mt-6 max-w-lg text-lg leading-8 text-[var(--muted)]">
            This demonstration intake collects the minimum information needed
            to evaluate a lead workflow. It is not a live legal service.
          </p>
          <p className="mt-8 text-sm text-[var(--muted)]">
            Reviewing submissions?{" "}
            <Link
              href="/login"
              className="font-semibold text-[var(--green)] underline decoration-[var(--coral)] decoration-2 underline-offset-4"
            >
              Sign in with Google
            </Link>
          </p>
        </section>
        <LeadForm />
      </main>
    </>
  );
}
