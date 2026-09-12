import { contract } from "./contract.js";

export type CapturedResendMessage = {
  body: string;
  receivedAt: string;
};

export class ResendStub {
  async reset(): Promise<void> {
    const response = await fetch(
      new URL("/__messages", contract.resend.origin),
      { method: "DELETE" },
    );
    if (!response.ok) {
      throw new Error(`Unable to reset Resend stub: HTTP ${response.status}`);
    }
  }

  async messages(): Promise<CapturedResendMessage[]> {
    const response = await fetch(
      new URL("/__messages", contract.resend.origin),
    );
    if (!response.ok) {
      throw new Error(`Unable to read Resend stub: HTTP ${response.status}`);
    }
    const payload = (await response.json()) as {
      messages: CapturedResendMessage[];
    };
    return payload.messages;
  }
}
