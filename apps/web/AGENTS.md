# AlmaPortal Web Agent Guidance

This file inherits every instruction from the repository root `AGENTS.md`. More specific guidance here may add constraints for `apps/web/**`, but it may not remove or weaken root guidance.

## Scope

- Changes in this module must stay within `apps/web/**`.
- Keep the browser free of app-managed Supabase access tokens. Protected API access goes through same-origin Next.js route handlers.
- Keep assessment data synthetic. UI copy must never imply that real PII or CVs are acceptable.
- Preserve keyboard access, visible focus, semantic HTML, and readable status/error messaging.
- Do not add a paid UI package or proprietary Alma assets.

## Immutable repository workflow

Root rules covering branch usage, frequent commits, push approval, pull request creation, CI completion, and squash workflow are inherited without modification. Reviews remain optional unless the user explicitly requests one for the current task. No push is permitted without the user's explicit approval in the same message.
