# NOTES: agent-generated vs hand-written

Almost all application source in this repository was produced by Cursor
agents under my direction. Commit authors are mine. That records ownership,
not that I typed the implementation.

I did not use Copilot autocomplete as the primary authoring path. I used
Cursor chats, Cursor subagents, and GitHub CLI.

## Hand-written or human-operated

These were not generated as product code:

- Architecture constraints: Supabase, Google OAuth, Python/FastAPI, Next.js,
  monorepo, hierarchical `AGENTS.md`
- Google Cloud Console OAuth client, origins, and redirect URI
- Resend account, API key, and sender choice (after SendGrid signup failed)
- Ignored env files (`.env`, `.env.local`, `.env.runtime`)
- Live browser QA, screenshots, and the bug reports that followed
- Branding screenshots I supplied for the logo and favicon
- Scope cuts: drop mandatory review agents, keep Playwright optional, ignore
  hosted deploy until local worked, switch mail to Resend

## Agent-generated

Treat these trees as agent-authored unless a later commit says otherwise:

- `apps/api/**`
- `apps/web/**` (including tests, route handlers, and UI)
- `infra/supabase/**`
- `tests/e2e/**`
- `.github/workflows/**`
- `Makefile`, root package and Python workspace files
- `docs/system-design.md`, root `README.md`, module `AGENTS.md` files
- CI, Render blueprint, and deployment workflow text

## Mixed: agent patch after I caught the failure

| Area | What the agent shipped | How I caught it | Fix |
| --- | --- | --- | --- |
| Resume control | Hidden file input, no selected-file text | Clicking Attach looked like a no-op | Native input + filename feedback (`b7f7a50`) |
| Public submit URL | Required `NEXT_PUBLIC_API_URL` with no local default | Form error "Lead submission is not configured" | Local loopback fallback plus env on the web process |
| Dev Makefile | `make dev-api` did not source `.env` / `.env.runtime` | Resend key existed, mail still hit the stub | Makefile loads both files before uvicorn |
| Mail provider | SendGrid adapter and stub | Twilio login blocked sending | Resend HTTP adapter and capture stub |
| Reviews | Three review agents on every change | Wall-clock cost | Reviews optional (`73f9a32`) |

## How to read git history

`main` squash-merge `#1` is the first vertical slice. Later commits on
`feat/resume-attachment-feedback` and `feat/resend-mailer` are also
agent-authored patches I requested after using the app.

Do not copy ignored env files into git. If an agent pastes a provider key
into chat or into `.env.example`, discard it and rotate the key.
