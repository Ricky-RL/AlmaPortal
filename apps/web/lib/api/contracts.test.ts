import { describe, expect, it } from "vitest";
import {
  normalizeLeadDetail,
  normalizeTicket,
} from "@/lib/api/contracts";

describe("FastAPI contract normalization", () => {
  it("accepts the API delivery array and lead field names", () => {
    const lead = normalizeLeadDetail({
      id: "lead-1",
      first_name: "Ada",
      last_name: "Lovelace",
      email: "ada@example.test",
      comments: "Please review visa timing.",
      resume_filename: "synthetic.pdf",
      resume_media_type: "application/pdf",
      resume_size_bytes: 1024,
      status: "REACHED_OUT",
      created_at: "2026-09-10T12:00:00Z",
      updated_at: "2026-09-11T12:00:00Z",
      reached_out_at: "2026-09-11T12:00:00Z",
      reached_out_by: { id: "reviewer-1", email: "reviewer@example.test" },
      deliveries: [
        {
          id: "delivery-1",
          kind: "prospect",
          state: "provider_accepted",
          attempt_count: 1,
          manual_retry_count: 0,
          last_attempt_at: "2026-09-10T12:01:00Z",
          provider_accepted: true,
          updated_at: "2026-09-10T12:01:02Z",
          attempts: [
            {
              id: "attempt-1",
              attempt_number: 1,
              state: "provider_accepted",
              outcome: "provider_accepted",
              trigger: "initial",
              reviewer: null,
              attempted_at: "2026-09-10T12:01:00Z",
              started_at: "2026-09-10T12:01:00Z",
              ended_at: "2026-09-10T12:01:02Z",
              provider_message_id: "provider-1",
              error: null,
              sanitized_error: null,
            },
          ],
        },
        {
          id: "delivery-2",
          delivery_kind: "attorney",
          state: "unknown",
          attempt_count: 2,
          manual_retry_count: 1,
          last_error_code: "timeout",
          updated_at: "2026-09-10T12:02:00Z",
          attempts: [
            {
              id: "attempt-2",
              attempt_number: 2,
              state: "unknown",
              outcome: "unknown",
              trigger: "manual",
              reviewer: {
                id: "reviewer-1",
                email: "reviewer@example.test",
              },
              attempted_at: "2026-09-10T12:02:00Z",
              started_at: "2026-09-10T12:02:00Z",
              ended_at: "2026-09-10T12:02:10Z",
              provider_message_id: null,
              error: "timeout",
              sanitized_error: "Delivery outcome is unknown.",
            },
          ],
        },
      ],
    });

    expect(lead.resumeName).toBe("synthetic.pdf");
    expect(lead.comments).toBe("Please review visa timing.");
    expect(lead.resumeSizeBytes).toBe(1024);
    expect(lead.deliveries.prospect).toMatchObject({
      id: "delivery-1",
      state: "provider_accepted",
      providerAccepted: true,
    });
    expect(lead.deliveries.attorney).toMatchObject({
      id: "delivery-2",
      state: "unknown",
      manualRetryCount: 1,
      lastErrorCode: "timeout",
    });
    expect(lead.deliveries.attorney.attempts).toEqual([
      expect.objectContaining({
        id: "attempt-2",
        attemptNumber: 2,
        state: "unknown",
        outcome: "unknown",
        trigger: "manual",
        reviewer: {
          id: "reviewer-1",
          email: "reviewer@example.test",
          name: undefined,
        },
        sanitizedError: "Delivery outcome is unknown.",
      }),
    ]);
    expect(lead.audit.map((event) => event.action)).toEqual([
      "Lead submitted",
      "Marked reached out",
    ]);
  });

  it("does not invent attempts when the API supplies an empty history", () => {
    const lead = normalizeLeadDetail({
      id: "lead-1",
      first_name: "Ada",
      last_name: "Lovelace",
      email: "ada@example.test",
      status: "PENDING",
      created_at: "2026-09-10T12:00:00Z",
      deliveries: [
        {
          id: "delivery-1",
          kind: "prospect",
          state: "processing",
          attempt_count: 1,
          attempts: [],
        },
      ],
    });

    expect(lead.deliveries.prospect.state).toBe("processing");
    expect(lead.deliveries.prospect.attempts).toEqual([]);
  });

  it("accepts the API's absolute 60-second ticket fields", () => {
    expect(
      normalizeTicket({
        url: "https://api.example.test/api/v1/downloads/resume?ticket=synthetic",
        expires_in_seconds: 60,
      }),
    ).toEqual({
      url: "https://api.example.test/api/v1/downloads/resume?ticket=synthetic",
      expiresIn: 60,
    });
  });
});
