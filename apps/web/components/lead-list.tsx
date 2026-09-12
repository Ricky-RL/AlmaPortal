"use client";

import { Search } from "lucide-react";
import Link from "next/link";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { Badge, Button, Card, Input } from "@/components/ui";
import {
  ApiError,
  getLeadSummary,
  searchLeads,
} from "@/lib/api/client";
import type {
  LeadListItem,
  LeadStatus,
  LeadSummary,
} from "@/lib/api/contracts";
import { formatDate } from "@/lib/utils";

const EMPTY_SUMMARY: LeadSummary = { total: 0, pending: 0, reachedOut: 0 };

export function LeadList() {
  const [summary, setSummary] = useState(EMPTY_SUMMARY);
  const [items, setItems] = useState<LeadListItem[]>([]);
  const [query, setQuery] = useState("");
  const [activeQuery, setActiveQuery] = useState("");
  const [status, setStatus] = useState<LeadStatus | "">("");
  const [cursor, setCursor] = useState<string | null>(null);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [cursorHistory, setCursorHistory] = useState<Array<string | null>>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();

  const load = useCallback(async () => {
    try {
      const [nextSummary, page] = await Promise.all([
        getLeadSummary(),
        searchLeads({ q: activeQuery, status, cursor, limit: 20 }),
      ]);
      setError(undefined);
      setSummary(nextSummary);
      setItems(page.items);
      setNextCursor(page.nextCursor);
    } catch (error) {
      setError(
        error instanceof ApiError
          ? error.message
          : "Lead data could not be loaded. Try again.",
      );
    } finally {
      setLoading(false);
    }
  }, [activeQuery, cursor, status]);

  useEffect(() => {
    const timeout = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timeout);
  }, [load]);

  function search(event: FormEvent) {
    event.preventDefault();
    setCursor(null);
    setCursorHistory([]);
    setActiveQuery(query.trim());
  }

  function changeStatus(value: string) {
    setStatus(value as LeadStatus | "");
    setCursor(null);
    setCursorHistory([]);
  }

  function nextPage() {
    if (!nextCursor) return;
    setCursorHistory((history) => [...history, cursor]);
    setCursor(nextCursor);
  }

  function previousPage() {
    setCursorHistory((history) => {
      const copy = [...history];
      setCursor(copy.pop() ?? null);
      return copy;
    });
  }

  return (
    <div>
      <section
        className="grid gap-4 sm:grid-cols-3"
        aria-label="Lead summary"
      >
        {[
          ["Total leads", summary.total],
          ["Pending", summary.pending],
          ["Reached out", summary.reachedOut],
        ].map(([label, value]) => (
          <Card key={label} className="p-5">
            <p className="text-sm font-semibold text-[var(--muted)]">{label}</p>
            <p className="mt-1 text-3xl font-bold">{value}</p>
          </Card>
        ))}
      </section>

      <Card className="mt-6">
        <form
          className="grid gap-3 md:grid-cols-[1fr_13rem_auto]"
          onSubmit={search}
          role="search"
        >
          <label>
            <span className="sr-only">Search lead details</span>
            <div className="relative">
              <Search
                className="absolute left-3.5 top-3.5 size-4 text-[var(--muted)]"
                aria-hidden="true"
              />
              <Input
                className="pl-10"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search name, email, or lead details"
              />
            </div>
          </label>
          <label>
            <span className="sr-only">Filter by status</span>
            <select
              className="min-h-11 w-full rounded-xl border border-[var(--line)] bg-white px-3.5"
              value={status}
              onChange={(event) => changeStatus(event.target.value)}
            >
              <option value="">All statuses</option>
              <option value="PENDING">Pending</option>
              <option value="REACHED_OUT">Reached out</option>
            </select>
          </label>
          <Button type="submit">Search</Button>
        </form>

        <div className="mt-7" aria-live="polite">
          {loading && (
            <div role="status" className="py-12 text-center text-[var(--muted)]">
              Loading leads…
            </div>
          )}
          {!loading && error && (
            <div
              className="rounded-2xl border border-red-200 bg-red-50 p-5 text-red-900"
              role="alert"
            >
              <p>{error}</p>
              <Button
                className="mt-4"
                variant="secondary"
                onClick={() => {
                  setLoading(true);
                  setError(undefined);
                  void load();
                }}
              >
                Try again
              </Button>
            </div>
          )}
          {!loading && !error && items.length === 0 && (
            <div className="py-12 text-center">
              <h2 className="text-lg font-bold">No matching leads</h2>
              <p className="mt-2 text-[var(--muted)]">
                Adjust the search or status filter.
              </p>
            </div>
          )}
          {!loading && !error && items.length > 0 && (
            <ul className="divide-y divide-[var(--line)]">
              {items.map((lead) => (
                <li key={lead.id}>
                  <Link
                    href={`/leads/${encodeURIComponent(lead.id)}`}
                    className="grid gap-2 rounded-xl px-2 py-5 hover:bg-[var(--cream)] focus-visible:outline-2 focus-visible:outline-offset-2 sm:grid-cols-[1fr_1fr_auto] sm:items-center"
                  >
                    <div>
                      <p className="font-bold">
                        {lead.firstName} {lead.lastName}
                      </p>
                      <p className="text-sm text-[var(--muted)]">{lead.email}</p>
                    </div>
                    <p className="text-sm text-[var(--muted)]">
                      Received {formatDate(lead.createdAt)}
                    </p>
                    <Badge
                      tone={
                        lead.status === "REACHED_OUT" ? "success" : "warning"
                      }
                    >
                      {lead.status === "REACHED_OUT"
                        ? "Reached out"
                        : "Pending"}
                    </Badge>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>

        {!loading && !error && items.length > 0 && (
          <nav
            className="mt-6 flex justify-between border-t border-[var(--line)] pt-5"
            aria-label="Lead pages"
          >
            <Button
              variant="secondary"
              onClick={previousPage}
              disabled={cursorHistory.length === 0}
            >
              Previous
            </Button>
            <Button
              variant="secondary"
              onClick={nextPage}
              disabled={!nextCursor}
            >
              Next
            </Button>
          </nav>
        )}
      </Card>
    </div>
  );
}
