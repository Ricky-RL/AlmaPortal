import { createHash } from "node:crypto";

import type { TestInfo } from "@playwright/test";

import { contract } from "../helpers/contract.js";
import { tinyPdf } from "./tiny-pdf.js";

export type UploadFixture = {
  name: string;
  mimeType: string;
  buffer: Buffer;
};

export type Prospect = {
  firstName: string;
  lastName: string;
  email: string;
  acknowledged: boolean;
  cv: UploadFixture;
};

export type LeadStatus = "PENDING" | "REACHED_OUT";

function slug(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 32);
}

export class SyntheticData {
  readonly emails = new Set<string>();
  private sequence = 0;
  private readonly testSlug: string;
  private readonly runToken: string;

  constructor(testInfo: TestInfo) {
    this.testSlug = slug(testInfo.title) || "test";
    this.runToken = createHash("sha256")
      .update(
        `${testInfo.workerIndex}:${testInfo.retry}:${testInfo.titlePath.join("/")}`,
      )
      .digest("hex")
      .slice(0, 8);
  }

  prospect(label = "prospect"): Prospect {
    this.sequence += 1;
    const recordSlug = `${this.testSlug}-${slug(label)}-${this.sequence}`;
    const email = `alma-e2e+${recordSlug}-${this.runToken}@${contract.data.emailDomain}`;
    this.emails.add(email);

    return {
      firstName: "Alma",
      lastName: `E2E ${label} ${this.sequence}`,
      email,
      acknowledged: true,
      cv: {
        ...tinyPdf,
        buffer: Buffer.from(tinyPdf.buffer),
      },
    };
  }
}
