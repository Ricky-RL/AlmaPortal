export function safeNextPath(value: string | null) {
  if (!value || !value.startsWith("/") || value.includes("\\")) {
    return "/leads";
  }
  try {
    const base = new URL("https://local.almaportal.invalid");
    const destination = new URL(value, base);
    return destination.origin === base.origin
      ? `${destination.pathname}${destination.search}${destination.hash}`
      : "/leads";
  } catch {
    return "/leads";
  }
}
