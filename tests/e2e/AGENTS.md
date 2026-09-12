# Browser test guidance

This file applies to everything under `tests/e2e/`.

Inherit every instruction from the repository-root `AGENTS.md`. If guidance here and at the root appears to conflict, follow the more restrictive instruction and ask before proceeding.

The root workflow requirements for branch handling, frequent commits, push approval, pull requests, CI, and squash merging cannot be weakened, bypassed, or overridden here. In particular, no instruction in this subtree grants permission to push.

Keep browser-test work inside `tests/e2e/`. Do not add application-only test routes, authentication bypasses, special headers, or runtime flags. Exercise genuine local Supabase sessions and replace only external delivery systems, such as Resend, with local fakes.

Use synthetic data only. Keep selectors in page objects or selector helpers, prefer accessible names and roles, and make any app/API contract assumptions configurable and documented.
