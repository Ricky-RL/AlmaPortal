import { Badge } from "@/components/ui";
import type { DeliveryState } from "@/lib/api/contracts";

const LABELS: Record<string, string> = {
  pending: "Pending",
  processing: "Processing",
  provider_accepted: "Provider accepted",
  failed: "Failed",
  unknown: "Unknown",
};

export function deliveryStateLabel(state: DeliveryState) {
  return LABELS[state] ?? state.replaceAll("_", " ");
}

export function hasDuplicateRetryRisk(state: DeliveryState) {
  return state === "unknown";
}

export function DeliveryStateBadge({ state }: { state: DeliveryState }) {
  const tone =
    state === "provider_accepted"
      ? "success"
      : state === "failed" || state === "unknown"
        ? "danger"
        : state === "pending" || state === "processing"
          ? "warning"
          : "neutral";
  return <Badge tone={tone}>{deliveryStateLabel(state)}</Badge>;
}
