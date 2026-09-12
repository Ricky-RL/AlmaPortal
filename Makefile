SHELL := /bin/sh
.DEFAULT_GOAL := help

PNPM ?= pnpm
UV ?= uv
SUPABASE ?= supabase

WEB_DIR := apps/web
API_DIR := apps/api
E2E_DIR := tests/e2e
SUPABASE_WORKDIR := infra
SUPABASE_SCRIPTS := infra/supabase/scripts
RUNTIME_ENV ?= .env.runtime
STORAGE_BUCKET ?= resumes
EMAIL_SMOKE_RECIPIENT ?=
DEMO_RESET_CONFIRM ?=
ALMA_API_PASSWORD ?=
COMMIT_SHA ?= $(shell git rev-parse --short HEAD 2>/dev/null || printf 'local-development')
export ALMA_API_PASSWORD COMMIT_SHA DEMO_RESET_CONFIRM EMAIL_SMOKE_RECIPIENT

.PHONY: help setup dev-web dev-api lint typecheck unit test-api test-web \
	test-e2e test test-integration db-check supabase-start supabase-stop supabase-reset \
	db-runtime-credentials email-smoke storage-audit demo-reset build ci

help:
	@printf '%s\n' \
		'setup                  Install pnpm and uv workspace dependencies' \
		'dev-web                Start the web development server' \
		'dev-api                Start the API development server' \
		'lint                   Lint TypeScript and Python' \
		'typecheck              Type-check TypeScript and Python' \
		'unit                   Run API and web unit tests' \
		'test-api               Run API tests' \
		'test-web               Run web tests' \
		'test-e2e               Run optional Playwright tests manually' \
		'test                   Run API and web unit tests' \
		'test-integration       Run database checks and optional Playwright tests' \
		'supabase-start         Start local Supabase' \
		'supabase-stop          Stop local Supabase' \
		'supabase-reset         Rebuild the local database from migrations' \
		'db-runtime-credentials Bootstrap alma_api and write mode-0600 runtime env' \
		'email-smoke            Send to EMAIL_SMOKE_RECIPIENT after explicit request' \
		'storage-audit          Audit private storage configuration' \
		'demo-reset             Dry-run, or apply with DEMO_RESET_CONFIRM=RESET-LOCAL-DEMO' \
		'build                  Build web assets and compile-check the API' \
		'ci                     Run all handoff checks'

setup:
	corepack enable
	$(PNPM) install
	$(UV) sync --all-packages --all-extras

dev-web:
	$(PNPM) --dir $(WEB_DIR) dev

dev-api:
	cd $(API_DIR) && $(UV) run alma-api

lint:
	$(PNPM) run lint
	cd $(API_DIR) && $(UV) run ruff check .

typecheck:
	$(PNPM) run typecheck
	cd $(API_DIR) && $(UV) run mypy src

unit: test-api test-web

test-api:
	cd $(API_DIR) && $(UV) run pytest

test-web:
	$(PNPM) --dir $(WEB_DIR) test

test-e2e:
	$(PNPM) --dir $(E2E_DIR) test

test: unit

test-integration: db-check test-e2e

db-check:
	$(SUPABASE) db lint --local --level warning --workdir $(SUPABASE_WORKDIR)
	$(SUPABASE) test db --workdir $(SUPABASE_WORKDIR)

supabase-start:
	@set -eu; \
	if [ -f .env ]; then set -a; . ./.env; set +a; fi; \
	export GOOGLE_CLIENT_ID="$${GOOGLE_CLIENT_ID:-replace-with-google-client-id}"; \
	export GOOGLE_CLIENT_SECRET="$${GOOGLE_CLIENT_SECRET:-replace-with-google-client-secret}"; \
	export GOOGLE_REDIRECT_URI="$${GOOGLE_REDIRECT_URI:-http://127.0.0.1:54321/auth/v1/callback}"; \
	$(SUPABASE) start --workdir $(SUPABASE_WORKDIR)

supabase-stop:
	$(SUPABASE) stop --no-backup --workdir $(SUPABASE_WORKDIR)

supabase-reset:
	$(SUPABASE) db reset --local --workdir $(SUPABASE_WORKDIR)

db-runtime-credentials:
	@set -eu; \
	status_file=$$(mktemp); \
	trap 'rm -f "$$status_file"' EXIT; \
	$(SUPABASE) status -o env --workdir $(SUPABASE_WORKDIR) > "$$status_file"; \
	set -a; . "$$status_file"; set +a; \
	publishable_key=$${PUBLISHABLE_KEY:-$${ANON_KEY:-}}; \
	secret_key=$${SECRET_KEY:-$${SERVICE_ROLE_KEY:-}}; \
	test -n "$${API_URL:-}" && test -n "$$publishable_key" && \
		test -n "$$secret_key" && test -n "$${DB_URL:-}" && \
		test -n "$${JWT_SECRET:-}"; \
	password=$${ALMA_API_PASSWORD:-$$($(UV) run --project $(API_DIR) python -c "import secrets; print(secrets.token_urlsafe(32))")}; \
	ALMA_API_PASSWORD="$$password" SUPABASE_DB_ADMIN_URL="$$DB_URL" \
		$(UV) run --project $(API_DIR) python $(SUPABASE_SCRIPTS)/bootstrap_api_role.py; \
	database_url=$$(ALMA_API_PASSWORD="$$password" SUPABASE_DB_ADMIN_URL="$$DB_URL" \
		$(UV) run --project $(API_DIR) python -c "import os; from urllib.parse import quote, urlsplit, urlunsplit; parsed = urlsplit(os.environ['SUPABASE_DB_ADMIN_URL']); port = f':{parsed.port}' if parsed.port else ''; auth = 'alma_api:' + quote(os.environ['ALMA_API_PASSWORD'], safe='') + '@'; print(urlunsplit((parsed.scheme, auth + (parsed.hostname or '') + port, parsed.path, parsed.query, parsed.fragment)))"); \
	umask 077; \
	{ \
		printf 'SUPABASE_URL=%s\n' "$$API_URL"; \
		printf 'NEXT_PUBLIC_SUPABASE_URL=%s\n' "$$API_URL"; \
		printf 'E2E_SUPABASE_URL=%s\n' "$$API_URL"; \
		printf 'SUPABASE_PUBLISHABLE_KEY=%s\n' "$$publishable_key"; \
		printf 'NEXT_PUBLIC_SUPABASE_ANON_KEY=%s\n' "$$publishable_key"; \
		printf 'E2E_SUPABASE_ANON_KEY=%s\n' "$$publishable_key"; \
		printf 'SUPABASE_SECRET_KEY=%s\n' "$$secret_key"; \
		printf 'SUPABASE_SERVICE_ROLE_KEY=%s\n' "$$secret_key"; \
		printf 'E2E_SUPABASE_SERVICE_ROLE_KEY=%s\n' "$$secret_key"; \
		printf 'SUPABASE_STORAGE_BUCKET=%s\n' "$(STORAGE_BUCKET)"; \
		printf 'SUPABASE_JWT_SECRET=%s\n' "$$JWT_SECRET"; \
		printf 'DATABASE_URL=%s\n' "$$database_url"; \
	} > "$(RUNTIME_ENV)"; \
	chmod 0600 "$(RUNTIME_ENV)"; \
	unset password database_url; \
	printf 'Wrote local runtime credentials to %s\n' "$(RUNTIME_ENV)"

email-smoke:
	@test -n "$$EMAIL_SMOKE_RECIPIENT" || { \
		printf 'Set EMAIL_SMOKE_RECIPIENT to an authorized unrelated address.\n' >&2; \
		exit 2; \
	}
	@cd $(API_DIR) && $(UV) run email-smoke \
		--to "$$EMAIL_SMOKE_RECIPIENT" \
		--confirm-unrelated-recipient

storage-audit:
	@set -eu; \
	status_file=$$(mktemp); \
	trap 'rm -f "$$status_file"' EXIT; \
	$(SUPABASE) status -o env --workdir $(SUPABASE_WORKDIR) > "$$status_file"; \
	set -a; . "$$status_file"; set +a; \
	secret_key=$${SECRET_KEY:-$${SERVICE_ROLE_KEY:-}}; \
	test -n "$${DB_URL:-}" && test -n "$${API_URL:-}" && test -n "$$secret_key"; \
	SUPABASE_DB_ADMIN_URL="$$DB_URL" SUPABASE_URL="$$API_URL" \
		SUPABASE_SERVICE_ROLE_KEY="$$secret_key" \
		$(UV) run --project $(API_DIR) python $(SUPABASE_SCRIPTS)/storage_reconcile.py

demo-reset:
	@if [ "$$DEMO_RESET_CONFIRM" = "RESET-LOCAL-DEMO" ]; then \
		$(SUPABASE_SCRIPTS)/demo_reset.sh --apply --confirm RESET-LOCAL-DEMO; \
	else \
		$(SUPABASE_SCRIPTS)/demo_reset.sh; \
	fi

build:
	$(PNPM) run build
	cd $(API_DIR) && $(UV) run python -m compileall -q src

ci: lint typecheck test db-check build
