import { afterEach, describe, expect, it, vi } from "vitest";
import {
  uploadErrorMessage,
  uploadPublicLead,
} from "@/lib/public-upload";

class FakeXmlHttpRequest {
  static last: FakeXmlHttpRequest;
  status = 429;
  response: unknown = { code: "budget_exceeded" };
  responseType = "";
  body?: FormData;
  readonly upload = {
    addEventListener: vi.fn(),
  };
  private readonly listeners = new Map<string, () => void>();

  constructor() {
    FakeXmlHttpRequest.last = this;
  }

  open() {}

  addEventListener(name: string, callback: () => void) {
    this.listeners.set(name, callback);
  }

  send(body: FormData) {
    this.body = body;
    queueMicrotask(() => this.listeners.get("load")?.());
  }
}

describe("public multipart upload", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends only the five API fields and maps capacity problems", async () => {
    process.env.NEXT_PUBLIC_API_URL = "https://api.example.test";
    vi.stubGlobal("XMLHttpRequest", FakeXmlHttpRequest);

    await expect(
      uploadPublicLead(
        {
          firstName: "Ada",
          lastName: "Lovelace",
          email: "ada@example.test",
          resume: new File(["synthetic"], "synthetic.pdf"),
          syntheticDataAcknowledged: true,
        },
        vi.fn(),
      ),
    ).rejects.toMatchObject({
      status: 429,
      code: "budget_exceeded",
      message: expect.stringMatching(/submission capacity/i),
    });

    expect([...FakeXmlHttpRequest.last.body!.keys()].sort()).toEqual([
      "email",
      "first_name",
      "last_name",
      "resume",
      "synthetic_data_acknowledged",
    ]);
  });

  it("sends comments only when they are present", async () => {
    process.env.NEXT_PUBLIC_API_URL = "https://api.example.test";
    vi.stubGlobal("XMLHttpRequest", FakeXmlHttpRequest);

    await expect(
      uploadPublicLead(
        {
          firstName: "Ada",
          lastName: "Lovelace",
          email: "ada@example.test",
          resume: new File(["synthetic"], "synthetic.pdf"),
          syntheticDataAcknowledged: true,
          comments: "Please review visa timing.",
        },
        vi.fn(),
      ),
    ).rejects.toMatchObject({ status: 429 });

    expect(FakeXmlHttpRequest.last.body!.get("comments")).toBe(
      "Please review visa timing.",
    );
  });

  it("maps every required public response status", () => {
    expect(uploadErrorMessage(413)).toMatch(/10 MiB/);
    expect(uploadErrorMessage(422)).toMatch(/validate/);
    expect(uploadErrorMessage(422, "unsupported_resume_format")).toMatch(
      /valid PDF, DOC, or DOCX/i,
    );
    expect(uploadErrorMessage(429)).toMatch(/too many submissions/i);
    expect(uploadErrorMessage(503)).toMatch(/temporarily unavailable/i);
    expect(uploadErrorMessage(429, "budget_exceeded")).toMatch(/capacity/i);
  });
});
