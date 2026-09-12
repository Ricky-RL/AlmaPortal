import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { LeadList } from "@/components/lead-list";
import { server } from "@/test/msw/server";

describe("lead list", () => {
  it("sends body search and status filters and follows cursor pagination", async () => {
    const requests: Array<Record<string, unknown>> = [];
    server.use(
      http.get("*/api/internal/csrf", () =>
        HttpResponse.json({ token: "csrf-token" }),
      ),
      http.get("*/api/internal/leads/summary", () =>
        HttpResponse.json({ total: 2, pending: 1, reached_out: 1 }),
      ),
      http.post("*/api/internal/leads/search", async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        requests.push(body);
        if (body.cursor === "page-2") {
          return HttpResponse.json({
            items: [
              {
                id: "lead-2",
                first_name: "Grace",
                last_name: "Hopper",
                email: "grace@example.test",
                status: "REACHED_OUT",
                created_at: "2026-09-11T12:00:00Z",
              },
            ],
            next_cursor: null,
          });
        }
        return HttpResponse.json({
          items: [
            {
              id: "lead-1",
              first_name: "Ada",
              last_name: "Lovelace",
              email: "ada@example.test",
              status: "PENDING",
              created_at: "2026-09-10T12:00:00Z",
            },
          ],
          next_cursor: "page-2",
        });
      }),
    );

    const user = userEvent.setup();
    render(<LeadList />);
    expect(await screen.findByText("Ada Lovelace")).toBeVisible();

    await user.type(
      screen.getByPlaceholderText(/search name, email/i),
      "contract",
    );
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Filter by status" }),
      "PENDING",
    );
    await user.click(screen.getByRole("button", { name: "Search" }));

    await waitFor(() =>
      expect(requests).toContainEqual({
        q: "contract",
        status: "PENDING",
        cursor: null,
        limit: 20,
      }),
    );

    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByText("Grace Hopper")).toBeVisible();
    expect(requests.at(-1)?.cursor).toBe("page-2");

    await user.click(screen.getByRole("button", { name: "Previous" }));
    expect(await screen.findByText("Ada Lovelace")).toBeVisible();
  });
});
