export function validatedDownloadTicketUrl(
  raw: string,
  configuredApiUrl = process.env.NEXT_PUBLIC_API_URL,
) {
  if (!configuredApiUrl) {
    throw new Error("The public API origin is not configured.");
  }

  const configured = new URL(configuredApiUrl);
  const localHttp =
    configured.protocol === "http:" &&
    (configured.hostname === "localhost" ||
      configured.hostname === "127.0.0.1");
  if (configured.protocol !== "https:" && !localHttp) {
    throw new Error("The public API origin is not secure.");
  }
  if (
    configured.username ||
    configured.password ||
    configured.search ||
    configured.hash
  ) {
    throw new Error("The public API origin is invalid.");
  }

  const ticket = new URL(raw);
  if (
    ticket.origin !== configured.origin ||
    ticket.username ||
    ticket.password
  ) {
    throw new Error("The download ticket origin is not allowed.");
  }
  return ticket.toString();
}
