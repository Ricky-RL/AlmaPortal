import type { Metadata, Viewport } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "AlmaPortal Assessment",
    template: "%s | AlmaPortal",
  },
  description: "Synthetic lead intake assessment for legal-services workflows.",
  robots: {
    index: false,
    follow: false,
    nocache: true,
    googleBot: { index: false, follow: false, noimageindex: true },
  },
};

export const viewport: Viewport = {
  colorScheme: "light",
  themeColor: "#f6f0e5",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <header className="border-b border-[var(--line)] bg-[color-mix(in_srgb,var(--cream)_90%,transparent)]">
          <div className="mx-auto flex max-w-6xl items-center justify-between px-5 py-4 sm:px-8">
            <Link
              href="/"
              className="text-lg font-bold tracking-tight focus-visible:rounded-sm focus-visible:outline-2 focus-visible:outline-offset-4"
            >
              Alma<span className="text-[var(--coral)]">Portal</span>
            </Link>
            <p className="text-sm font-medium text-[var(--muted)]">
              Assessment environment
            </p>
          </div>
        </header>
        {children}
      </body>
    </html>
  );
}
