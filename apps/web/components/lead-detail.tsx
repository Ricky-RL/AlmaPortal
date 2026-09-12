"use client";

import { ArrowLeft, Download, RotateCw, Send } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import {
  DeliveryStateBadge,
  hasDuplicateRetryRisk,
} from "@/components/delivery-state";
import { Badge, Button, Card } from "@/components/ui";
import {
  getLead,
  reachOut,
  requestResumeTicket,
  retryDelivery,
} from "@/lib/api/client";
import type {
  DeliveryProjection,
  LeadDetail as LeadDetailModel,
} from "@/lib/api/contracts";
import { validatedDownloadTicketUrl } from "@/lib/api/ticket";
import { formatDate } from "@/lib/utils";

function DeliveryCard({
  leadId,
  delivery,
  onUpdated,
}: {
  leadId: string;
  delivery: DeliveryProjection;
  onUpdated: (lead: LeadDetailModel) => void;
}) {
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const duplicateRisk = hasDuplicateRetryRisk(delivery.state);
  const isPending = delivery.state === "pending";
  const canRetry =
    isPending || delivery.state === "failed" || delivery.state === "unknown";

  async function retry() {
    setBusy(true);
    setError(undefined);
    try {
      onUpdated(
        await retryDelivery(leadId, {
          deliveryId: delivery.id,
          confirmDuplicateRisk: duplicateRisk ? confirmed : false,
        }),
      );
      setConfirmed(false);
    } catch {
      setError(
        isPending
          ? "The pending notification could not be sent."
          : "The notification could not be retried.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-lg font-bold capitalize">
          {delivery.audience} notification
        </h3>
        <DeliveryStateBadge state={delivery.state} />
      </div>
      <p className="mt-3 text-sm text-[var(--muted)]">
        Last updated {formatDate(delivery.updatedAt)}
      </p>
      <p className="mt-1 text-sm text-[var(--muted)]">
        {delivery.attemptCount} total attempt
        {delivery.attemptCount === 1 ? "" : "s"}, {delivery.manualRetryCount} manual
        {delivery.manualRetryCount === 1 ? " retry" : " retries"}
      </p>

      {(delivery.providerAccepted ||
        delivery.state === "provider_accepted") && (
        <p className="mt-4 rounded-xl bg-emerald-50 p-3 text-sm leading-6 text-emerald-950">
          Provider accepted means the delivery provider accepted responsibility
          for the message. It does not prove that the message reached the
          recipient&apos;s inbox.
        </p>
      )}

      {canRetry && (
        <div className="mt-5 border-t border-[var(--line)] pt-5">
          {duplicateRisk && (
            <label className="mb-4 flex items-start gap-3 rounded-xl bg-red-50 p-3 text-sm text-red-950">
              <input
                className="mt-1 size-4"
                type="checkbox"
                checked={confirmed}
                onChange={(event) => setConfirmed(event.target.checked)}
              />
              <span>
                I understand that the prior outcome is{" "}
                {delivery.state.toLowerCase()}. Retrying may send a duplicate
                notification.
              </span>
            </label>
          )}
          <Button
            type="button"
            variant="secondary"
            disabled={busy || (duplicateRisk && !confirmed)}
            onClick={retry}
          >
            {isPending ? (
              <Send className="mr-2 size-4" aria-hidden="true" />
            ) : (
              <RotateCw className="mr-2 size-4" aria-hidden="true" />
            )}
            {busy
              ? isPending
                ? "Sending…"
                : "Retrying…"
              : isPending
                ? "Send pending notification"
                : "Retry notification"}
          </Button>
          {error && (
            <p className="mt-3 text-sm font-medium text-red-800" role="alert">
              {error}
            </p>
          )}
        </div>
      )}

      <div className="mt-5">
        <h4 className="font-semibold">Attempt history</h4>
        {delivery.attempts.length === 0 ? (
          <p className="mt-2 text-sm text-[var(--muted)]">
            No delivery attempts recorded.
          </p>
        ) : (
          <ol className="mt-2 divide-y divide-[var(--line)]">
            {delivery.attempts.map((attempt) => (
              <li className="py-3 text-sm" key={attempt.id}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <DeliveryStateBadge state={attempt.state} />
                  <time className="text-[var(--muted)]">
                    {formatDate(attempt.attemptedAt)}
                  </time>
                </div>
                <p className="mt-2 text-[var(--muted)]">
                  Attempt {attempt.attemptNumber}.{" "}
                  {attempt.trigger === "manual" ? "Manual retry" : "Initial send"}
                  {attempt.reviewer?.email
                    ? ` by ${attempt.reviewer.email}`
                    : ""}
                </p>
                {attempt.endedAt && (
                  <p className="mt-1 text-[var(--muted)]">
                    Completed {formatDate(attempt.endedAt)}
                  </p>
                )}
                {attempt.providerMessageId && (
                  <p className="mt-2 break-all text-[var(--muted)]">
                    Provider ID: {attempt.providerMessageId}
                  </p>
                )}
                {attempt.sanitizedError && (
                  <p className="mt-2 text-red-800">
                    {attempt.sanitizedError}
                  </p>
                )}
              </li>
            ))}
          </ol>
        )}
      </div>
    </Card>
  );
}

export function LeadDetail({
  id,
  navigate = (url) => window.location.assign(url),
}: {
  id: string;
  navigate?: (url: string) => void;
}) {
  const [lead, setLead] = useState<LeadDetailModel>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();
  const [showStatusConfirmation, setShowStatusConfirmation] = useState(false);
  const [actionBusy, setActionBusy] = useState(false);
  const [actionError, setActionError] = useState<string>();

  const load = useCallback(async () => {
    try {
      const nextLead = await getLead(id);
      setError(undefined);
      setLead(nextLead);
    } catch {
      setError("This lead could not be loaded.");
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    const timeout = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timeout);
  }, [load]);

  async function confirmReachedOut() {
    setActionBusy(true);
    setActionError(undefined);
    try {
      setLead(await reachOut(id));
      setShowStatusConfirmation(false);
    } catch {
      setActionError("The lead status could not be updated.");
    } finally {
      setActionBusy(false);
    }
  }

  async function downloadResume() {
    setActionBusy(true);
    setActionError(undefined);
    try {
      const ticket = await requestResumeTicket(id);
      if (!ticket.url) throw new Error("Missing ticket.");
      navigate(validatedDownloadTicketUrl(ticket.url));
    } catch {
      setActionError("A resume download could not be prepared.");
    } finally {
      setActionBusy(false);
    }
  }

  if (loading) {
    return (
      <main className="mx-auto max-w-6xl px-5 py-12 sm:px-8" role="status">
        Loading lead…
      </main>
    );
  }

  if (error || !lead) {
    return (
      <main className="mx-auto max-w-6xl px-5 py-12 sm:px-8">
        <Card role="alert">
          <h1 className="text-xl font-bold">Lead unavailable</h1>
          <p className="mt-2 text-[var(--muted)]">{error}</p>
          <Button
            className="mt-5"
            variant="secondary"
            onClick={() => {
              setLoading(true);
              setError(undefined);
              void load();
            }}
          >
            Try again
          </Button>
        </Card>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-6xl px-5 py-10 sm:px-8">
      <Link
        href="/leads"
        className="inline-flex items-center text-sm font-semibold text-[var(--green)] hover:underline"
      >
        <ArrowLeft className="mr-2 size-4" aria-hidden="true" />
        All leads
      </Link>

      <div className="mt-6 flex flex-wrap items-start justify-between gap-5">
        <div>
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-3xl font-bold tracking-tight">
              {lead.firstName} {lead.lastName}
            </h1>
            <Badge tone={lead.status === "REACHED_OUT" ? "success" : "warning"}>
              {lead.status === "REACHED_OUT" ? "Reached out" : "Pending"}
            </Badge>
          </div>
          <p className="mt-2 text-[var(--muted)]">{lead.email}</p>
        </div>
        <div className="flex flex-wrap gap-3">
          <Button
            type="button"
            variant="secondary"
            onClick={downloadResume}
            disabled={actionBusy || !lead.resumeName}
          >
            <Download className="mr-2 size-4" aria-hidden="true" />
            Download CV
          </Button>
          {lead.status === "PENDING" && (
            <Button
              type="button"
              onClick={() => setShowStatusConfirmation(true)}
              disabled={actionBusy}
            >
              Mark reached out
            </Button>
          )}
        </div>
      </div>

      {showStatusConfirmation && (
        <Card
          className="mt-6 border-[var(--coral)] bg-orange-50"
          role="alertdialog"
          aria-labelledby="status-confirmation-title"
        >
          <h2 id="status-confirmation-title" className="text-lg font-bold">
            Confirm outreach
          </h2>
          <p className="mt-2 text-sm leading-6">
            Confirm that outreach occurred. This changes the lead from Pending
            to Reached out and records an audit event.
          </p>
          <div className="mt-4 flex gap-3">
            <Button
              type="button"
              onClick={confirmReachedOut}
              disabled={actionBusy}
            >
              {actionBusy ? "Saving…" : "Confirm reached out"}
            </Button>
            <Button
              type="button"
              variant="secondary"
              onClick={() => setShowStatusConfirmation(false)}
              disabled={actionBusy}
            >
              Cancel
            </Button>
          </div>
        </Card>
      )}

      {actionError && (
        <p
          className="mt-5 rounded-xl bg-red-50 p-3 font-medium text-red-900"
          role="alert"
        >
          {actionError}
        </p>
      )}

      <section className="mt-7 grid gap-5 md:grid-cols-2">
        <Card className="p-5">
          <h2 className="text-lg font-bold">Lead data</h2>
          <dl className="mt-4 grid gap-4 text-sm">
            <div>
              <dt className="font-semibold text-[var(--muted)]">Lead ID</dt>
              <dd className="mt-1 break-all">{lead.id}</dd>
            </div>
            <div>
              <dt className="font-semibold text-[var(--muted)]">Resume</dt>
              <dd className="mt-1">{lead.resumeName ?? "Not available"}</dd>
            </div>
            <div>
              <dt className="font-semibold text-[var(--muted)]">Resume type</dt>
              <dd className="mt-1">{lead.resumeMediaType ?? "Not recorded"}</dd>
            </div>
            <div>
              <dt className="font-semibold text-[var(--muted)]">Resume size</dt>
              <dd className="mt-1">
                {lead.resumeSizeBytes === null
                  ? "Not recorded"
                  : `${(lead.resumeSizeBytes / 1024).toFixed(1)} KiB`}
              </dd>
            </div>
            <div>
              <dt className="font-semibold text-[var(--muted)]">Submitted</dt>
              <dd className="mt-1">{formatDate(lead.createdAt)}</dd>
            </div>
            <div>
              <dt className="font-semibold text-[var(--muted)]">Last updated</dt>
              <dd className="mt-1">{formatDate(lead.updatedAt)}</dd>
            </div>
            {lead.reachedOutAt && (
              <div>
                <dt className="font-semibold text-[var(--muted)]">
                  Reached out
                </dt>
                <dd className="mt-1">
                  {formatDate(lead.reachedOutAt)}
                  {lead.reachedOutBy?.email
                    ? ` by ${lead.reachedOutBy.email}`
                    : ""}
                </dd>
              </div>
            )}
          </dl>
        </Card>

        <Card className="p-5">
          <h2 className="text-lg font-bold">Audit trail</h2>
          {lead.audit.length === 0 ? (
            <p className="mt-4 text-sm text-[var(--muted)]">
              No audit events recorded.
            </p>
          ) : (
            <ol className="mt-3 divide-y divide-[var(--line)]">
              {lead.audit.map((event) => (
                <li className="py-3 text-sm" key={event.id}>
                  <p className="font-semibold">{event.action}</p>
                  <p className="mt-1 text-[var(--muted)]">
                    {formatDate(event.occurredAt)}
                    {event.actor ? ` by ${event.actor}` : ""}
                  </p>
                  {event.detail && <p className="mt-2">{event.detail}</p>}
                </li>
              ))}
            </ol>
          )}
        </Card>
      </section>

      <section className="mt-7" aria-labelledby="notification-heading">
        <h2 id="notification-heading" className="mb-4 text-2xl font-bold">
          Notification delivery
        </h2>
        <div className="grid gap-5 lg:grid-cols-2">
          <DeliveryCard
            leadId={lead.id}
            delivery={lead.deliveries.prospect}
            onUpdated={setLead}
          />
          <DeliveryCard
            leadId={lead.id}
            delivery={lead.deliveries.attorney}
            onUpdated={setLead}
          />
        </div>
      </section>
    </main>
  );
}
