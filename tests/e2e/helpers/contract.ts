import "dotenv/config";

function env(name: string, fallback: string): string {
  return process.env[name]?.trim() || fallback;
}

function integerEnv(name: string, fallback: number): number {
  const raw = process.env[name];
  if (!raw) {
    return fallback;
  }

  const parsed = Number.parseInt(raw, 10);
  if (!Number.isSafeInteger(parsed) || parsed <= 0) {
    throw new Error(`${name} must be a positive integer, received "${raw}"`);
  }
  return parsed;
}

function pathEnv(name: string, fallback: string): string {
  const value = env(name, fallback);
  return value.startsWith("/") ? value : `/${value}`;
}

function optionalPathEnv(name: string): string | undefined {
  const value = process.env[name]?.trim();
  if (!value) return undefined;
  return value.startsWith("/") ? value : `/${value}`;
}

export const contract = {
  webBaseUrl: env("E2E_WEB_BASE_URL", "http://127.0.0.1:3000"),
  apiBaseUrl: env("E2E_API_BASE_URL", "http://127.0.0.1:8000"),
  supabaseUrl: env("E2E_SUPABASE_URL", "http://127.0.0.1:54321"),
  supabaseAnonKey: process.env.E2E_SUPABASE_ANON_KEY?.trim() ?? "",
  supabaseServiceRoleKey:
    process.env.E2E_SUPABASE_SERVICE_ROLE_KEY?.trim() ?? "",
  auth: {
    email: env("E2E_AUTH_EMAIL", "dashboard@alma-e2e.invalid"),
    password: env(
      "E2E_AUTH_PASSWORD",
      "Alma-e2e-local-only-2026!",
    ),
  },
  paths: {
    publicForm: pathEnv("E2E_PUBLIC_FORM_PATH", "/"),
    success: optionalPathEnv("E2E_SUCCESS_PATH"),
    login: pathEnv("E2E_LOGIN_PATH", "/login"),
    dashboard: pathEnv("E2E_DASHBOARD_PATH", "/leads"),
    submissionApi: pathEnv("E2E_SUBMISSION_API_PATH", "/api/v1/leads"),
  },
  fields: {
    firstName: env("E2E_FIELD_FIRST_NAME", "first_name"),
    lastName: env("E2E_FIELD_LAST_NAME", "last_name"),
    email: env("E2E_FIELD_EMAIL", "email"),
    acknowledged: env(
      "E2E_FIELD_ACKNOWLEDGED",
      "synthetic_data_acknowledged",
    ),
    cv: env("E2E_FIELD_CV", "resume"),
    comments: env("E2E_FIELD_COMMENTS", "comments"),
  },
  data: {
    leadsTable: env("E2E_LEADS_TABLE", "leads"),
    notificationsTable: env(
      "E2E_NOTIFICATIONS_TABLE",
      "email_deliveries",
    ),
    leadIdColumn: env("E2E_LEAD_ID_COLUMN", "id"),
    leadEmailColumn: env("E2E_LEAD_EMAIL_COLUMN", "normalized_email"),
    leadStatusColumn: env("E2E_LEAD_STATUS_COLUMN", "status"),
    notificationLeadIdColumn: env(
      "E2E_NOTIFICATION_LEAD_ID_COLUMN",
      "lead_id",
    ),
    notificationStatusColumn: env(
      "E2E_NOTIFICATION_STATUS_COLUMN",
      "state",
    ),
    storageBucket: env("E2E_STORAGE_BUCKET", "resumes"),
    storagePathColumn: env(
      "E2E_STORAGE_PATH_COLUMN",
      "resume_object_path",
    ),
    emailDomain: env("E2E_TEST_EMAIL_DOMAIN", "alma-e2e.invalid"),
    cursorFixtureCount: integerEnv("E2E_CURSOR_FIXTURE_COUNT", 26),
    maxUploadBytes: integerEnv("E2E_MAX_UPLOAD_BYTES", 10 * 1024 * 1024),
  },
  sendgrid: {
    origin: env(
      "E2E_SENDGRID_STUB_ORIGIN",
      "http://127.0.0.1:4319",
    ),
    startStub: env("E2E_START_SENDGRID_STUB", "true") !== "false",
  },
} as const;

export function apiUrl(path: string): string {
  return new URL(path, contract.apiBaseUrl).toString();
}

export function webUrl(path: string): string {
  return new URL(path, contract.webBaseUrl).toString();
}

export function requireSupabaseEnvironment(): void {
  const missing = [
    ["E2E_SUPABASE_ANON_KEY", contract.supabaseAnonKey],
    ["E2E_SUPABASE_SERVICE_ROLE_KEY", contract.supabaseServiceRoleKey],
  ]
    .filter(([, value]) => !value)
    .map(([name]) => name);

  if (missing.length > 0) {
    throw new Error(
      `Missing ${missing.join(", ")}. Copy local Supabase values into tests/e2e/.env.`,
    );
  }

  const host = new URL(contract.supabaseUrl).hostname;
  const isLocal =
    host === "localhost" || host === "127.0.0.1" || host === "::1";
  if (!isLocal && process.env.E2E_ALLOW_REMOTE_SUPABASE !== "true") {
    throw new Error(
      `Refusing to mutate non-local Supabase host "${host}". Set E2E_ALLOW_REMOTE_SUPABASE=true only for an isolated disposable environment.`,
    );
  }
}

export function requireExternalDeliveryIsolation(): void {
  const configured = process.env.SENDGRID_BASE_URL?.trim();
  if (!configured) {
    throw new Error(
      "SENDGRID_BASE_URL must be present in the E2E environment so email isolation can be verified.",
    );
  }

  const configuredUrl = new URL(configured);
  const stubUrl = new URL(contract.sendgrid.origin);
  const isLoopback = ["localhost", "127.0.0.1", "::1"].includes(
    configuredUrl.hostname,
  );
  if (!isLoopback || configuredUrl.origin !== stubUrl.origin) {
    throw new Error(
      `SENDGRID_BASE_URL must match the local E2E stub origin ${stubUrl.origin}; received ${configuredUrl.origin}.`,
    );
  }
}
