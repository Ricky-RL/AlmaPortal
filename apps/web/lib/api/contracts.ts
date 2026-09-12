export type LeadStatus = "PENDING" | "REACHED_OUT" | (string & {});
export type DeliveryState =
  | "pending"
  | "processing"
  | "provider_accepted"
  | "failed"
  | "unknown"
  | (string & {});
export type DeliveryKind = "prospect" | "attorney";

export type Reviewer = {
  id: string;
  email: string;
  name?: string;
};

export type LeadSummary = {
  total: number;
  pending: number;
  reachedOut: number;
};

export type LeadListItem = {
  id: string;
  firstName: string;
  lastName: string;
  email: string;
  status: LeadStatus;
  createdAt: string;
};

export type LeadSearchPage = {
  items: LeadListItem[];
  nextCursor: string | null;
};

export type DeliveryAttempt = {
  id: string;
  attemptNumber: number;
  state: DeliveryState;
  outcome: DeliveryState | null;
  trigger: string;
  reviewer: Reviewer | null;
  attemptedAt: string | null;
  startedAt: string | null;
  endedAt: string | null;
  error: string | null;
  sanitizedError: string | null;
  providerMessageId: string | null;
};

export type DeliveryProjection = {
  id: string;
  audience: DeliveryKind;
  state: DeliveryState;
  providerAccepted: boolean;
  updatedAt: string | null;
  attemptCount: number;
  manualRetryCount: number;
  lastErrorCode: string | null;
  lastError: string | null;
  providerMessageId: string | null;
  attempts: DeliveryAttempt[];
};

export type AuditEvent = {
  id: string;
  action: string;
  actor: string | null;
  occurredAt: string | null;
  detail: string | null;
};

export type LeadDetail = LeadListItem & {
  comments: string | null;
  resumeName: string | null;
  resumeMediaType: string | null;
  resumeSizeBytes: number | null;
  updatedAt: string | null;
  reachedOutAt: string | null;
  reachedOutBy: Reviewer | null;
  audit: AuditEvent[];
  deliveries: {
    prospect: DeliveryProjection;
    attorney: DeliveryProjection;
  };
};

export type RetryRequest = {
  deliveryId: string;
  confirmDuplicateRisk: boolean;
};

type UnknownRecord = Record<string, unknown>;

function record(value: unknown): UnknownRecord {
  return value && typeof value === "object" ? (value as UnknownRecord) : {};
}

function unwrap(value: unknown) {
  const root = record(value);
  return root.data && typeof root.data === "object" ? record(root.data) : root;
}

function pick(source: UnknownRecord, ...keys: string[]) {
  for (const key of keys) {
    if (source[key] !== undefined && source[key] !== null) return source[key];
  }
  return undefined;
}

function text(value: unknown, fallback = "") {
  return typeof value === "string" ? value : fallback;
}

function count(value: unknown) {
  const number = typeof value === "number" ? value : Number(value);
  return Number.isFinite(number) ? number : 0;
}

function normalizeStatus(value: unknown, fallback = "UNKNOWN") {
  return text(value, fallback).toUpperCase() as LeadStatus;
}

function normalizeDeliveryState(
  value: unknown,
  fallback: DeliveryState = "unknown",
): DeliveryState {
  const state = text(value).toLowerCase();
  if (state === "pending") return "pending";
  if (["processing", "queued", "sending"].includes(state)) return "processing";
  if (["provider_accepted", "delivered"].includes(state)) {
    return "provider_accepted";
  }
  if (["failed", "known_failure"].includes(state)) return "failed";
  if (["unknown", "expired"].includes(state)) return "unknown";
  return fallback;
}

function normalizeAttempt(value: unknown, index: number): DeliveryAttempt {
  const item = record(value);
  const rawOutcome = pick(item, "outcome");
  const error =
    text(pick(item, "error", "error_message", "errorMessage")) || null;
  const sanitizedError =
    text(pick(item, "sanitized_error", "sanitizedError")) || error;
  return {
    id: text(pick(item, "id", "attempt_id", "attemptId"), `attempt-${index}`),
    attemptNumber:
      count(pick(item, "attempt_number", "attemptNumber")) || index + 1,
    state: normalizeDeliveryState(pick(item, "state", "status", "outcome")),
    outcome:
      rawOutcome === null || rawOutcome === undefined
        ? null
        : normalizeDeliveryState(rawOutcome),
    trigger: text(pick(item, "trigger"), "initial").toLowerCase(),
    reviewer: pick(item, "reviewer")
      ? normalizeReviewer(pick(item, "reviewer"))
      : null,
    attemptedAt:
      text(
        pick(item, "attempted_at", "attemptedAt", "started_at", "startedAt"),
      ) || null,
    startedAt: text(pick(item, "started_at", "startedAt")) || null,
    endedAt: text(pick(item, "ended_at", "endedAt")) || null,
    error,
    sanitizedError,
    providerMessageId:
      text(pick(item, "provider_message_id", "providerMessageId")) || null,
  };
}

function normalizeDelivery(
  value: unknown,
  audience: DeliveryKind,
): DeliveryProjection {
  const item = record(value);
  const attempts = pick(item, "attempts", "attempt_history", "attemptHistory");
  const accepted = pick(item, "provider_accepted", "providerAccepted");
  const state = normalizeDeliveryState(
    pick(item, "state", "status", "delivery_state", "deliveryState"),
    "pending",
  );
  const id = text(pick(item, "id", "delivery_id", "deliveryId"));
  const lastAttemptAt =
    text(pick(item, "last_attempt_at", "lastAttemptAt")) || null;
  const lastErrorCode =
    text(pick(item, "last_error_code", "lastErrorCode")) || null;
  const hasRealAttemptHistory = Array.isArray(attempts);
  const normalizedAttempts = hasRealAttemptHistory
    ? attempts.map((attempt, index) => normalizeAttempt(attempt, index))
    : [];
  if (
    !hasRealAttemptHistory &&
    (lastAttemptAt || count(pick(item, "attempt_count", "attemptCount")) > 0)
  ) {
    normalizedAttempts.push({
      id: `${id || audience}-latest`,
      attemptNumber: count(pick(item, "attempt_count", "attemptCount")) || 1,
      state,
      outcome: state === "processing" ? null : state,
      trigger: "initial",
      reviewer: null,
      attemptedAt: lastAttemptAt,
      startedAt: lastAttemptAt,
      endedAt: null,
      error: lastErrorCode,
      sanitizedError: lastErrorCode,
      providerMessageId: null,
    });
  }
  return {
    id,
    audience,
    state,
    providerAccepted:
      typeof accepted === "boolean"
        ? accepted
        : state === "provider_accepted",
    updatedAt:
      text(pick(item, "updated_at", "updatedAt", "last_attempt_at")) || null,
    attemptCount: count(pick(item, "attempt_count", "attemptCount")),
    manualRetryCount: count(
      pick(item, "manual_retry_count", "manualRetryCount"),
    ),
    lastErrorCode,
    lastError:
      text(pick(item, "last_error", "lastError", "last_error_code")) || null,
    providerMessageId:
      text(pick(item, "provider_message_id", "providerMessageId")) || null,
    attempts: normalizedAttempts,
  };
}

export function normalizeReviewer(value: unknown): Reviewer {
  const item = unwrap(value);
  return {
    id: text(pick(item, "id", "user_id", "userId")),
    email: text(item.email),
    name: text(pick(item, "name", "full_name", "fullName")) || undefined,
  };
}

export function normalizeSummary(value: unknown): LeadSummary {
  const item = unwrap(value);
  return {
    total: count(pick(item, "total", "total_count", "totalCount")),
    pending: count(pick(item, "pending", "pending_count", "pendingCount")),
    reachedOut: count(
      pick(item, "reached_out", "reachedOut", "reached_out_count"),
    ),
  };
}

export function normalizeLeadListItem(value: unknown): LeadListItem {
  const item = record(value);
  return {
    id: text(pick(item, "id", "lead_id", "leadId")),
    firstName: text(pick(item, "first_name", "firstName")),
    lastName: text(pick(item, "last_name", "lastName")),
    email: text(item.email),
    status: normalizeStatus(item.status, "PENDING"),
    createdAt: text(pick(item, "created_at", "createdAt")),
  };
}

export function normalizeSearchPage(value: unknown): LeadSearchPage {
  const item = unwrap(value);
  const items = pick(item, "items", "leads", "results");
  return {
    items: Array.isArray(items) ? items.map(normalizeLeadListItem) : [],
    nextCursor:
      text(pick(item, "next_cursor", "nextCursor", "cursor")) || null,
  };
}

export function normalizeLeadDetail(value: unknown): LeadDetail {
  const item = unwrap(value);
  const base = normalizeLeadListItem(item);
  const rawDeliveries = pick(item, "notifications", "deliveries");
  const notifications = record(rawDeliveries);
  const deliveryList = Array.isArray(rawDeliveries) ? rawDeliveries : [];
  const prospectDelivery = deliveryList.find((value) => {
    const delivery = record(value);
    const kind = text(pick(delivery, "kind", "delivery_kind")).toLowerCase();
    return kind === "prospect" || kind === "prospect_confirmation";
  });
  const attorneyDelivery = deliveryList.find((value) => {
    const delivery = record(value);
    const kind = text(pick(delivery, "kind", "delivery_kind")).toLowerCase();
    return kind === "attorney" || kind === "attorney_notification";
  });
  const rawAudit = pick(item, "audit", "audit_events", "auditEvents");
  const reachedOut = record(pick(item, "reached_out_by", "reachedOutBy"));
  const reachedOutAt =
    text(pick(item, "reached_out_at", "reachedOutAt")) || null;
  const fallbackAudit: unknown[] = [
    {
      id: `${base.id}-submitted`,
      action: "Lead submitted",
      occurred_at: base.createdAt,
      actor: "system",
    },
  ];
  if (reachedOutAt) {
    fallbackAudit.push({
      id: `${base.id}-reached-out`,
      action: "Marked reached out",
      occurred_at: reachedOutAt,
      actor: pick(reachedOut, "email", "name"),
    });
  }
  const audit = Array.isArray(rawAudit) ? rawAudit : fallbackAudit;
  return {
    ...base,
    comments: text(pick(item, "comments")) || null,
    resumeName:
      text(
        pick(
          item,
          "resume_filename",
          "resume_name",
          "resumeName",
          "cv_filename",
        ),
      ) || null,
    resumeMediaType:
      text(pick(item, "resume_media_type", "resumeMediaType")) || null,
    resumeSizeBytes:
      pick(item, "resume_size_bytes", "resumeSizeBytes") === undefined
        ? null
        : count(pick(item, "resume_size_bytes", "resumeSizeBytes")),
    updatedAt: text(pick(item, "updated_at", "updatedAt")) || null,
    reachedOutAt,
    reachedOutBy: Object.keys(reachedOut).length
      ? normalizeReviewer(reachedOut)
      : null,
    audit: audit.map((value, index) => {
          const event = record(value);
          return {
            id: text(pick(event, "id", "event_id"), `audit-${index}`),
            action: text(pick(event, "action", "event", "type"), "Updated"),
            actor: text(pick(event, "actor", "actor_email", "actorEmail")) || null,
            occurredAt:
              text(
                pick(event, "occurred_at", "occurredAt", "created_at", "createdAt"),
              ) || null,
            detail: text(pick(event, "detail", "message", "description")) || null,
          };
        }),
    deliveries: {
      prospect: normalizeDelivery(
        prospectDelivery ??
          pick(notifications, "prospect", "prospect_notification"),
        "prospect",
      ),
      attorney: normalizeDelivery(
        attorneyDelivery ??
          pick(notifications, "attorney", "attorney_notification"),
        "attorney",
      ),
    },
  };
}

export function normalizeTicket(value: unknown) {
  const item = unwrap(value);
  const url = text(pick(item, "url", "ticket_url", "ticketUrl", "download_url"));
  const expiresIn =
    count(pick(item, "expires_in", "expiresIn", "expires_in_seconds")) || 60;
  return { url, expiresIn };
}
