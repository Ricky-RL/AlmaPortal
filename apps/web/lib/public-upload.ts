export const MAX_RESUME_BYTES = 10 * 1024 * 1024;
export const ACCEPTED_RESUME_EXTENSIONS = [".pdf", ".doc", ".docx"] as const;

export type PublicLeadPayload = {
  firstName: string;
  lastName: string;
  email: string;
  resume: File;
  syntheticDataAcknowledged: true;
};

export class UploadError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    public readonly code?: string,
  ) {
    super(message);
    this.name = "UploadError";
  }
}

export function publicLeadEndpoint(raw = process.env.NEXT_PUBLIC_API_URL) {
  if (!raw) throw new Error("Lead submission is not configured.");

  const url = new URL(raw);
  const localHttp =
    url.protocol === "http:" &&
    (url.hostname === "localhost" || url.hostname === "127.0.0.1");
  if (url.protocol !== "https:" && !localHttp) {
    throw new Error("Lead submission requires a secure API URL.");
  }
  if (url.username || url.password || url.search || url.hash) {
    throw new Error("The configured API URL is invalid.");
  }

  const basePath = url.pathname.replace(/\/+$/, "");
  return `${url.origin}${basePath}/api/v1/leads`;
}

export function uploadErrorMessage(status: number, code?: string) {
  if (code?.includes("capacity") || code?.includes("budget")) {
    return "This assessment has reached its submission capacity. No more leads can be accepted right now.";
  }
  switch (status) {
    case 413:
      return "The resume is too large. Choose a file no larger than 10 MiB.";
    case 422:
      return "We could not validate those details. Check each field and try again.";
    case 429:
      return "Too many submissions were received. Wait a moment and try again.";
    case 503:
      return "Submission is temporarily unavailable. Please try again shortly.";
    default:
      return "We could not submit the form. Please try again.";
  }
}

export type PublicUploader = (
  payload: PublicLeadPayload,
  onProgress: (percentage: number) => void,
) => Promise<void>;

function problemCode(value: unknown) {
  if (!value || typeof value !== "object") return undefined;
  const code = (value as Record<string, unknown>).code;
  return typeof code === "string" ? code : undefined;
}

export const uploadPublicLead: PublicUploader = (payload, onProgress) =>
  new Promise((resolve, reject) => {
    let endpoint: string;
    try {
      endpoint = publicLeadEndpoint();
    } catch (error) {
      reject(error);
      return;
    }

    const body = new FormData();
    body.set("first_name", payload.firstName);
    body.set("last_name", payload.lastName);
    body.set("email", payload.email);
    body.set("resume", payload.resume);
    body.set("synthetic_data_acknowledged", "true");

    const request = new XMLHttpRequest();
    request.open("POST", endpoint);
    request.responseType = "json";
    request.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable) {
        onProgress(Math.min(100, Math.round((event.loaded / event.total) * 100)));
      }
    });
    request.addEventListener("load", () => {
      if (request.status >= 200 && request.status < 300) {
        onProgress(100);
        resolve();
        return;
      }
      const code = problemCode(request.response);
      reject(
        new UploadError(
          request.status,
          uploadErrorMessage(request.status, code),
          code,
        ),
      );
    });
    request.addEventListener("error", () => {
      reject(new UploadError(0, uploadErrorMessage(0)));
    });
    request.addEventListener("timeout", () => {
      reject(new UploadError(0, uploadErrorMessage(0)));
    });
    request.send(body);
  });
