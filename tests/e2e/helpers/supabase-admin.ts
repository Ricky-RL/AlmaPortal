import { randomUUID } from "node:crypto";

import { createServerClient } from "@supabase/ssr";
import {
  createClient,
  type Session,
  type SupabaseClient,
  type User,
} from "@supabase/supabase-js";
import type { BrowserContext } from "@playwright/test";

import type {
  LeadStatus,
  Prospect,
} from "../fixtures/synthetic-data.js";
import { contract, requireSupabaseEnvironment } from "./contract.js";

type MutableCookie = {
  name: string;
  value: string;
  options: {
    httpOnly?: boolean;
    maxAge?: number;
    sameSite?: boolean | "lax" | "strict" | "none";
    secure?: boolean;
  };
};

type PlaywrightCookie = Parameters<BrowserContext["addCookies"]>[0][number];

function sameSite(
  value: MutableCookie["options"]["sameSite"],
): "Strict" | "Lax" | "None" | undefined {
  if (value === "strict") return "Strict";
  if (value === "none") return "None";
  if (value === "lax" || value === true) return "Lax";
  return undefined;
}

function toPlaywrightCookie(cookie: MutableCookie): PlaywrightCookie {
  const result: PlaywrightCookie = {
    name: cookie.name,
    value: cookie.value,
    url: contract.webBaseUrl,
    httpOnly: cookie.options.httpOnly ?? false,
    secure:
      cookie.options.secure ?? new URL(contract.webBaseUrl).protocol === "https:",
  };
  const normalizedSameSite = sameSite(cookie.options.sameSite);
  if (normalizedSameSite) {
    result.sameSite = normalizedSameSite;
  }
  if (cookie.options.maxAge && cookie.options.maxAge > 0) {
    result.expires = Math.floor(Date.now() / 1000) + cookie.options.maxAge;
  }
  return result;
}

export class LocalSupabaseAdmin {
  readonly client: SupabaseClient;

  constructor() {
    requireSupabaseEnvironment();
    this.client = createClient(
      contract.supabaseUrl,
      contract.supabaseServiceRoleKey,
      {
        auth: {
          autoRefreshToken: false,
          detectSessionInUrl: false,
          persistSession: false,
        },
      },
    );
  }

  async ensureSyntheticGoogleUser(): Promise<User> {
    const users = await this.client.auth.admin.listUsers({
      page: 1,
      perPage: 1000,
    });
    if (users.error) {
      throw new Error(`Unable to list local auth users: ${users.error.message}`);
    }

    const existing = users.data.users.find(
      (user) => user.email?.toLowerCase() === contract.auth.email.toLowerCase(),
    );
    const attributes = {
      password: contract.auth.password,
      email_confirm: true,
      app_metadata: {
        provider: "google",
        providers: ["google"],
        alma_e2e: true,
      },
      user_metadata: {
        full_name: "Alma E2E Dashboard User",
        name: "Alma E2E Dashboard User",
      },
    };

    if (existing) {
      const updated = await this.client.auth.admin.updateUserById(
        existing.id,
        attributes,
      );
      if (updated.error) {
        throw new Error(
          `Unable to update local auth user: ${updated.error.message}`,
        );
      }
      return updated.data.user;
    }

    const created = await this.client.auth.admin.createUser({
      email: contract.auth.email,
      ...attributes,
    });
    if (created.error) {
      throw new Error(
        `Unable to create local auth user: ${created.error.message}`,
      );
    }
    return created.data.user;
  }

  async signInSyntheticUser(): Promise<Session> {
    await this.ensureSyntheticGoogleUser();
    const authClient = createClient(
      contract.supabaseUrl,
      contract.supabaseAnonKey,
      {
        auth: {
          autoRefreshToken: false,
          detectSessionInUrl: false,
          persistSession: false,
        },
      },
    );
    const result = await authClient.auth.signInWithPassword({
      email: contract.auth.email,
      password: contract.auth.password,
    });
    if (result.error || !result.data.session) {
      throw new Error(
        `Unable to obtain a genuine local Supabase session: ${
          result.error?.message ?? "session missing"
        }`,
      );
    }
    return result.data.session;
  }

  async installSsrSession(context: BrowserContext): Promise<void> {
    const session = await this.signInSyntheticUser();
    const cookieJar = new Map<string, MutableCookie>();
    const changedCookies: MutableCookie[] = [];

    const ssrClient = createServerClient(
      contract.supabaseUrl,
      contract.supabaseAnonKey,
      {
        cookies: {
          getAll() {
            return [...cookieJar.values()].map(({ name, value }) => ({
              name,
              value,
            }));
          },
          setAll(cookies) {
            for (const cookie of cookies) {
              const normalized: MutableCookie = {
                name: cookie.name,
                value: cookie.value,
                options: cookie.options,
              };
              cookieJar.set(cookie.name, normalized);
              changedCookies.push(normalized);
            }
          },
        },
      },
    );

    const installed = await ssrClient.auth.setSession({
      access_token: session.access_token,
      refresh_token: session.refresh_token,
    });
    if (installed.error) {
      throw new Error(
        `Unable to serialize the Supabase SSR session: ${installed.error.message}`,
      );
    }
    const verified = await ssrClient.auth.getUser();
    if (
      verified.error ||
      !verified.data.user ||
      verified.data.user.id !== session.user.id
    ) {
      throw new Error(
        `Serialized Supabase SSR session could not be verified: ${
          verified.error?.message ?? "user mismatch"
        }`,
      );
    }

    const browserCookies = changedCookies
      .filter((cookie) => cookie.value.length > 0)
      .map(toPlaywrightCookie);
    if (browserCookies.length === 0) {
      throw new Error("Supabase SSR did not emit an authentication cookie.");
    }
    await context.addCookies(browserCookies);
  }

  async setLeadState(
    email: string,
    leadStatus: LeadStatus,
  ): Promise<string> {
    const lead = await this.client
      .from(contract.data.leadsTable)
      .select(contract.data.leadIdColumn)
      .eq(contract.data.leadEmailColumn, email)
      .single();
    if (lead.error) {
      throw new Error(
        `Unable to find synthetic lead "${email}": ${lead.error.message}`,
      );
    }
    const id = (lead.data as unknown as Record<string, unknown>)[
      contract.data.leadIdColumn
    ];
    if (typeof id !== "string") {
      throw new Error(`Synthetic lead "${email}" has no string id.`);
    }

    const leadUpdate: Record<string, unknown> = {
      [contract.data.leadStatusColumn]: leadStatus,
    };
    if (leadStatus === "REACHED_OUT") {
      const reviewer = await this.ensureSyntheticGoogleUser();
      leadUpdate.reached_out_at = new Date().toISOString();
      leadUpdate.reached_out_by_user_id = reviewer.id;
      leadUpdate.reached_out_by_email = contract.auth.email;
    }

    const updatedLead = await this.client
      .from(contract.data.leadsTable)
      .update(leadUpdate)
      .eq(contract.data.leadIdColumn, id);
    if (updatedLead.error) {
      throw new Error(
        `Unable to set lead status for "${email}": ${updatedLead.error.message}`,
      );
    }

    return id;
  }

  async seedLeadList(prospects: Prospect[]): Promise<void> {
    const rows = prospects.map((prospect) => {
      const id = randomUUID();
      const objectId = randomUUID();
      return {
        id,
        first_name: prospect.firstName,
        last_name: prospect.lastName,
        [contract.data.leadEmailColumn]: prospect.email.toLowerCase(),
        [contract.data.storagePathColumn]: `leads/${id}/${objectId}.pdf`,
        original_filename: prospect.cv.name,
        detected_media_type: prospect.cv.mimeType,
        byte_size: prospect.cv.buffer.byteLength,
        [contract.data.leadStatusColumn]: "PENDING",
      };
    });
    const inserted = await this.client
      .from(contract.data.leadsTable)
      .insert(rows as never);
    if (inserted.error) {
      throw new Error(
        `Unable to seed synthetic lead-list data: ${inserted.error.message}`,
      );
    }
  }

  async seedRetryableUnknownLead(prospect: Prospect): Promise<void> {
    const id = randomUUID();
    const objectId = randomUUID();
    const oldAttempt = new Date(Date.now() - 2 * 60_000).toISOString();
    const insertedLead = await this.client
      .from(contract.data.leadsTable)
      .insert({
        id,
        first_name: prospect.firstName,
        last_name: prospect.lastName,
        [contract.data.leadEmailColumn]: prospect.email.toLowerCase(),
        [contract.data.storagePathColumn]: `leads/${id}/${objectId}.pdf`,
        original_filename: prospect.cv.name,
        detected_media_type: prospect.cv.mimeType,
        byte_size: prospect.cv.buffer.byteLength,
        [contract.data.leadStatusColumn]: "PENDING",
      } as never);
    if (insertedLead.error) {
      throw new Error(
        `Unable to seed unknown-delivery lead: ${insertedLead.error.message}`,
      );
    }

    const insertedDeliveries = await this.client
      .from(contract.data.notificationsTable)
      .insert([
        {
          [contract.data.notificationLeadIdColumn]: id,
          delivery_kind: "prospect",
          [contract.data.notificationStatusColumn]: "unknown",
          retry_count: 0,
          last_attempt_at: oldAttempt,
          recipient: prospect.email.toLowerCase(),
          last_error: "synthetic_unknown_provider_outcome",
        },
        {
          [contract.data.notificationLeadIdColumn]: id,
          delivery_kind: "attorney",
          [contract.data.notificationStatusColumn]: "provider_accepted",
          retry_count: 0,
          last_attempt_at: oldAttempt,
          recipient: `attorney@${contract.data.emailDomain}`,
          provider_message_id: "alma-e2e-accepted",
        },
      ] as never);
    if (insertedDeliveries.error) {
      throw new Error(
        `Unable to seed delivery projections: ${insertedDeliveries.error.message}`,
      );
    }
  }
}
