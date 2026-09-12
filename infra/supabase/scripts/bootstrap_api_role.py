#!/usr/bin/env python3
"""Install or rotate the alma_api password without exposing the secret."""

from __future__ import annotations

import argparse
import getpass
import os
import sys

try:
    import psycopg
    from psycopg import sql
except ImportError as exc:  # pragma: no cover - operator guidance
    raise SystemExit(
        "psycopg is required; install infra/supabase/scripts/requirements.txt"
    ) from exc


ROLE_NAME = "alma_api"
PASSWORD_ENV = "ALMA_API_PASSWORD"
ADMIN_URL_ENV = "SUPABASE_DB_ADMIN_URL"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Set or rotate the password for the least-privilege alma_api role."
    )
    parser.add_argument(
        "--admin-url-env",
        default=ADMIN_URL_ENV,
        help=f"environment variable containing the admin database URL (default: {ADMIN_URL_ENV})",
    )
    return parser.parse_args()


def read_runtime_password() -> str:
    password = os.environ.pop(PASSWORD_ENV, None)
    if password is None:
        password = getpass.getpass(f"New password for {ROLE_NAME}: ")
        confirmation = getpass.getpass("Confirm password: ")
        if password != confirmation:
            raise SystemExit("Password confirmation did not match.")

    if len(password) < 24:
        raise SystemExit("Runtime role password must be at least 24 characters.")
    if "\x00" in password or "\n" in password or "\r" in password:
        raise SystemExit("Runtime role password contains a forbidden control character.")
    return password


def main() -> int:
    args = parse_args()
    admin_url = os.environ.get(args.admin_url_env)
    if not admin_url:
        raise SystemExit(
            f"Set {args.admin_url_env} to an administrator PostgreSQL connection URL."
        )

    password = read_runtime_password()

    try:
        with psycopg.connect(admin_url, autocommit=False) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select rolcanlogin, rolsuper, rolcreatedb, rolcreaterole,
                           rolinherit, rolreplication, rolbypassrls
                      from pg_catalog.pg_roles
                     where rolname = %s
                    """,
                    (ROLE_NAME,),
                )
                attributes = cursor.fetchone()
                if attributes is None:
                    raise SystemExit(
                        "alma_api does not exist. Apply Supabase migrations first."
                    )

                expected = (True, False, False, False, False, False, False)
                if tuple(attributes) != expected:
                    raise SystemExit(
                        "alma_api has unexpected privileges; refusing credential rotation."
                    )

                # sql.Literal quotes the password safely. The statement and secret are
                # never printed, persisted, or included in process arguments.
                cursor.execute(
                    sql.SQL("alter role {} password {}").format(
                        sql.Identifier(ROLE_NAME),
                        sql.Literal(password),
                    )
                )
            connection.commit()
    finally:
        password = "\0" * len(password)

    print("alma_api credential installed successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
