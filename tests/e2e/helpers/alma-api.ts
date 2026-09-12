import type {
  APIRequestContext,
  APIResponse,
} from "@playwright/test";

import type { Prospect } from "../fixtures/synthetic-data.js";
import { apiUrl, contract } from "./contract.js";

export class AlmaApiClient {
  constructor(private readonly request: APIRequestContext) {}

  async submitProspect(prospect: Prospect): Promise<APIResponse> {
    const response = await this.request.post(
      apiUrl(contract.paths.submissionApi),
      {
        multipart: {
          [contract.fields.firstName]: prospect.firstName,
          [contract.fields.lastName]: prospect.lastName,
          [contract.fields.email]: prospect.email,
          [contract.fields.acknowledged]: String(prospect.acknowledged),
          ...(prospect.comments
            ? { [contract.fields.comments]: prospect.comments }
            : {}),
          [contract.fields.cv]: {
            name: prospect.cv.name,
            mimeType: prospect.cv.mimeType,
            buffer: prospect.cv.buffer,
          },
        },
      },
    );
    if (!response.ok()) {
      throw new Error(
        `Synthetic lead submission failed with HTTP ${response.status()}: ${await response.text()}`,
      );
    }
    return response;
  }

  async submitMany(prospects: Prospect[]): Promise<void> {
    const concurrency = 4;
    for (let index = 0; index < prospects.length; index += concurrency) {
      await Promise.all(
        prospects
          .slice(index, index + concurrency)
          .map((prospect) => this.submitProspect(prospect)),
      );
    }
  }
}
