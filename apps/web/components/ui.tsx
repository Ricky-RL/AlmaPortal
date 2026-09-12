import * as React from "react";
import { cn } from "@/lib/utils";

export function Button({
  className,
  variant = "primary",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "danger";
}) {
  return (
    <button
      className={cn(
        "inline-flex min-h-11 items-center justify-center rounded-full px-5 py-2.5 text-sm font-semibold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--coral)] focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-55",
        variant === "primary" &&
          "bg-[var(--green)] text-white hover:bg-[var(--green-light)]",
        variant === "secondary" &&
          "border border-[var(--line)] bg-white text-[var(--ink)] hover:bg-[var(--cream-deep)]",
        variant === "danger" &&
          "bg-[var(--coral)] text-[var(--ink)] hover:brightness-95",
        className,
      )}
      {...props}
    />
  );
}

export function Input({
  className,
  ...props
}: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        "min-h-11 w-full rounded-xl border border-[var(--line)] bg-white px-3.5 py-2.5 text-base text-[var(--ink)] shadow-sm outline-none placeholder:text-[var(--muted)] focus:border-[var(--green)] focus:ring-2 focus:ring-[color-mix(in_srgb,var(--green)_20%,transparent)] disabled:bg-stone-100",
        className,
      )}
      {...props}
    />
  );
}

export function Card({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "rounded-3xl border border-[var(--line)] bg-[var(--paper)] p-6 shadow-[0_18px_60px_rgba(29,47,41,0.07)]",
        className,
      )}
      {...props}
    />
  );
}

export function Badge({
  children,
  tone = "neutral",
}: {
  children: React.ReactNode;
  tone?: "neutral" | "success" | "warning" | "danger";
}) {
  return (
    <span
      className={cn(
        "inline-flex rounded-full px-2.5 py-1 text-xs font-semibold",
        tone === "neutral" && "bg-stone-200 text-stone-700",
        tone === "success" && "bg-emerald-100 text-emerald-900",
        tone === "warning" && "bg-amber-100 text-amber-900",
        tone === "danger" && "bg-red-100 text-red-900",
      )}
    >
      {children}
    </span>
  );
}

export function FieldError({ id, message }: { id: string; message?: string }) {
  if (!message) return null;
  return (
    <p id={id} className="mt-1.5 text-sm font-medium text-red-800" role="alert">
      {message}
    </p>
  );
}
