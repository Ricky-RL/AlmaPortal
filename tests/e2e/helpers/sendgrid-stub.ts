import { contract } from "./contract.js";

export type CapturedSendgridMessage = {
  body: string;
  receivedAt: string;
};

export class SendgridStub {
  async reset(): Promise<void> {
    const response = await fetch(
      new URL("/__messages", contract.sendgrid.origin),
      { method: "DELETE" },
    );
    if (!response.ok) {
      throw new Error(`Unable to reset SendGrid stub: HTTP ${response.status}`);
    }
  }

  async messages(): Promise<CapturedSendgridMessage[]> {
    const response = await fetch(
      new URL("/__messages", contract.sendgrid.origin),
    );
    if (!response.ok) {
      throw new Error(`Unable to read SendGrid stub: HTTP ${response.status}`);
    }
    const payload = (await response.json()) as {
      messages: CapturedSendgridMessage[];
    };
    return payload.messages;
  }
}
