# Coding-agent usage

I built this take-home in Cursor. Cursor subagents implemented disjoint modules
in parallel (repo foundation, Supabase, FastAPI, Next.js, browser tests, docs).
Three review agents (architect, devil's advocate, senior engineer) critiqued
the plan before coding. Later I used the same setup for targeted bug fixes.
GitHub CLI handled the PR. I verified the product in the browser, not from
green unit tests alone.

I delegated almost all of the code: migrations, API, UI, CI, and the design
doc. I kept the product calls: Supabase plus Google OAuth, Python FastAPI, a
monorepo, and hierarchical `AGENTS.md` files. I also cut work that was burning
the clock: mandatory three-agent code reviews, Playwright as a CI gate, and
hosted deploy before a working local demo. I created the Google OAuth client
and Resend account myself, filled ignored env files, and clicked through the
real form whenever an agent said a path was done.

One miss: the resume control nested a visually hidden file input inside a
label. Unit tests assigned a `FileList` in JavaScript and passed. In the
browser, choosing a file showed no filename, so the control looked broken. I
caught it by attaching a resume. The fix was a native input plus visible
selected-file feedback (`b7f7a50`). A similar class of miss: `make dev-api`
did not load `.env` / `.env.runtime`, so after Resend credentials existed the
process still talked to the local mail stub until I restarted it from the repo
root.

## Representative prompt logs

Excerpts from Cursor sessions on 12 Sep 2026. Secrets and inbox addresses are
removed.

### 1. Plan, constraints, and review agents

> help me plan out this project. For some context this is a take home
> assesement from tryalma.
>
> - Im thinking of using supabase for the database and then google oauth
>   through supabase to manage the accounts
> - the backend should be python
> - this should be the project monorepo
>
> commit regularly. Do NOT commit to main. instead push changes to a new
> branch with a PR, spawn an agent to review the changes, and then merge it
> into main once the review agent gives the green light
>
> use hierarchical AI files. At the root of the repo have an agents.md file
> with the overall description and then there should be an additional
> agents.md file under each module
>
> When you are down your plan spawn 3 agents to review the plan and to
> critique it. ... Spawn a senior architect, a devils advocate and a senior
> software engineer agents as the reviewers

What I kept: the stack and the `AGENTS.md` layout. What I later reversed: the
mandatory review-agent gate, because it delayed merges more than it caught
defects.

### 2. Parallel implementation

After the plan passed review, the orchestrating agent created `feat/alma-lead-portal`
and launched six implementation tracks with non-overlapping file ownership
(governance, Supabase, FastAPI, Next.js, browser tests, documentation). I did
not write those modules by hand. I directed scope, then used the running app
as the acceptance test.

### 3. Live QA over a green test suite

> the attachment is broken when i go in to attach a resume then nothing happens

> this is what i see when i try to submit
> [screenshot: "Lead submission is not configured."]

> for now dont worry about prod, just focus on getting it to work locally

> you dont need to run the playwright tests, from here on out only add
> backend unit tests since playwright takes too long to run

> update the agents md file so that it doesnt require three other agents to
> review the code, we no longer need the reviewers as it takes too long

The agent treated missing `NEXT_PUBLIC_API_URL` as a production-config
problem. I was on loopback. The form had no FastAPI origin because the web
process was not given `apps/web/.env.local`. I caught that from the screenshot,
not from CI.

### 4. Provider swap when SendGrid blocked signup

> help me set up the email portion of this project so that the emails send out

> sendgrid doeest work i cant sign in. what is an alternative tool that i can
> use, or is there something that can be ran locally

> lets switch to resend then. i have the resend api key

> port 8000 is the backend running locally. the goal is to get the project
> working locally

The mailer is a port. Switching providers did not require rewriting domain
rules. The operational miss was process env: an old API process kept the stub
base URL until it was killed and started through `make dev-api`.
