"use client";

import { ChevronDown } from "lucide-react";
import { useActionState, useEffect, useId, useRef, useState } from "react";
import { Button } from "@/components/ui";
import { signOutReviewer } from "@/lib/auth-actions";
import { cn } from "@/lib/utils";

export function ReviewerAccountMenu({ email }: { email?: string | null }) {
  const [open, setOpen] = useState(false);
  const [error, action, pending] = useActionState(signOutReviewer, undefined);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuId = useId();
  const label = email?.trim() || "Account";

  useEffect(() => {
    if (!open) return;

    function onPointerDown(event: PointerEvent) {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    }

    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      setOpen(false);
      triggerRef.current?.focus();
    }

    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  return (
    <div ref={rootRef} className="relative max-w-full">
      <button
        ref={triggerRef}
        type="button"
        className="inline-flex min-h-11 max-w-full items-center gap-1.5 rounded-full px-2.5 text-sm text-[var(--muted)] transition hover:bg-[var(--cream-deep)] hover:text-[var(--ink)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--coral)] focus-visible:ring-offset-2"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={menuId}
        onClick={() => setOpen((current) => !current)}
      >
        <span className="truncate">{label}</span>
        <ChevronDown
          aria-hidden="true"
          className={cn("size-4 shrink-0 transition", open && "rotate-180")}
        />
      </button>
      {open ? (
        <div
          id={menuId}
          role="menu"
          aria-label="Account"
          className="absolute right-0 z-20 mt-1 min-w-48 rounded-2xl border border-[var(--line)] bg-[var(--paper)] p-2 shadow-[0_18px_60px_rgba(29,47,41,0.12)]"
        >
          <form action={action}>
            <Button
              type="submit"
              variant="secondary"
              role="menuitem"
              className="w-full px-4"
              disabled={pending}
            >
              {pending ? "Signing out…" : "Sign out"}
            </Button>
          </form>
        </div>
      ) : null}
      {error ? (
        <p
          className="absolute right-0 mt-1 max-w-52 text-right text-xs font-medium text-red-800"
          role="alert"
        >
          {error}
        </p>
      ) : null}
    </div>
  );
}
