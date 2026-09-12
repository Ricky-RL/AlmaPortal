#!/usr/bin/env python3
"""Plan resume-storage reconciliation and optionally apply an reviewed plan."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

try:
    import psycopg
except ImportError as exc:  # pragma: no cover - operator guidance
    raise SystemExit(
        "psycopg is required; install infra/supabase/scripts/requirements.txt"
    ) from exc


ADMIN_URL_ENV = "SUPABASE_DB_ADMIN_URL"
SUPABASE_URL_ENV = "SUPABASE_URL"
SERVICE_KEY_ENV = "SUPABASE_SERVICE_ROLE_KEY"
CONFIRMATION = "PURGE-ORPHAN-RESUMES"
PLAN_VERSION = 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create a read-only reconciliation plan by default. Applying requires "
            "a previously written plan and an explicit confirmation token."
        )
    )
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "--plan-out",
        type=pathlib.Path,
        help="write the dry-run JSON plan to this path",
    )
    action.add_argument(
        "--apply-plan",
        type=pathlib.Path,
        help="apply orphan deletions from a prior JSON plan",
    )
    parser.add_argument("--confirm", help=argparse.SUPPRESS)
    return parser.parse_args()


def connect() -> psycopg.Connection[Any]:
    admin_url = os.environ.get(ADMIN_URL_ENV)
    if not admin_url:
        raise SystemExit(f"Set {ADMIN_URL_ENV} to an administrator database URL.")
    return psycopg.connect(admin_url)


def build_plan(connection: psycopg.Connection[Any]) -> dict[str, Any]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            select o.name,
                   coalesce((o.metadata ->> 'size')::bigint, 0) as object_bytes,
                   o.created_at
              from storage.objects as o
              left join public.leads as l
                on l.resume_object_path = o.name
             where o.bucket_id = 'resumes'
               and l.id is null
             order by o.name
            """
        )
        orphan_objects = [
            {
                "path": path,
                "byte_size": byte_size,
                "created_at": created_at.isoformat() if created_at else None,
            }
            for path, byte_size, created_at in cursor.fetchall()
        ]

        cursor.execute(
            """
            select l.id, l.resume_object_path, l.byte_size
              from public.leads as l
              left join storage.objects as o
                on o.bucket_id = 'resumes'
               and o.name = l.resume_object_path
             where o.id is null
             order by l.created_at, l.id
            """
        )
        missing_objects = [
            {
                "lead_id": str(lead_id),
                "path": path,
                "expected_byte_size": byte_size,
            }
            for lead_id, path, byte_size in cursor.fetchall()
        ]

    now = dt.datetime.now(dt.timezone.utc)
    return {
        "version": PLAN_VERSION,
        "generated_at": now.isoformat(),
        "bucket": "resumes",
        "dry_run": True,
        "orphan_objects": orphan_objects,
        "missing_objects": missing_objects,
        "summary": {
            "orphan_object_count": len(orphan_objects),
            "orphan_object_bytes": sum(
                item["byte_size"] for item in orphan_objects
            ),
            "missing_object_count": len(missing_objects),
        },
    }


def print_plan(plan: dict[str, Any]) -> None:
    print(json.dumps(plan, indent=2, sort_keys=True))


def object_is_still_orphan(
    connection: psycopg.Connection[Any], object_path: str
) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            select exists (
                select 1
                  from storage.objects as o
                 where o.bucket_id = 'resumes'
                   and o.name = %s
            )
            and not exists (
                select 1
                  from public.leads as l
                 where l.resume_object_path = %s
            )
            """,
            (object_path, object_path),
        )
        row = cursor.fetchone()
        return bool(row and row[0])


def delete_via_storage_api(base_url: str, service_key: str, object_path: str) -> None:
    encoded_path = urllib.parse.quote(object_path, safe="/")
    url = f"{base_url.rstrip('/')}/storage/v1/object/resumes/{encoded_path}"
    request = urllib.request.Request(
        url,
        method="DELETE",
        headers={
            "Authorization": f"Bearer {service_key}",
            "apikey": service_key,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.status not in (200, 204):
                raise RuntimeError(
                    f"Storage API returned HTTP {response.status} for {object_path}"
                )
    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            f"Storage API returned HTTP {exc.code} for {object_path}"
        ) from exc


def load_plan(path: pathlib.Path) -> dict[str, Any]:
    plan = json.loads(path.read_text(encoding="utf-8"))
    if plan.get("version") != PLAN_VERSION or plan.get("bucket") != "resumes":
        raise SystemExit("Plan version or bucket is not supported.")

    generated_at = dt.datetime.fromisoformat(plan["generated_at"])
    if generated_at.tzinfo is None:
        raise SystemExit("Plan timestamp must include a timezone.")
    if dt.datetime.now(dt.timezone.utc) - generated_at > dt.timedelta(hours=24):
        raise SystemExit("Plan is older than 24 hours. Generate and review a new plan.")

    return plan


def apply_plan(plan: dict[str, Any]) -> int:
    base_url = os.environ.get(SUPABASE_URL_ENV)
    service_key = os.environ.get(SERVICE_KEY_ENV)
    if not base_url or not service_key:
        raise SystemExit(
            f"Set {SUPABASE_URL_ENV} and {SERVICE_KEY_ENV} to apply a plan."
        )

    deleted = 0
    skipped = 0
    with connect() as connection:
        for item in plan.get("orphan_objects", []):
            object_path = item["path"]
            if not object_is_still_orphan(connection, object_path):
                skipped += 1
                continue
            delete_via_storage_api(base_url, service_key, object_path)
            deleted += 1

    print(f"Deleted {deleted} orphan object(s); skipped {skipped} changed object(s).")
    return 0


def main() -> int:
    args = parse_args()
    if args.apply_plan:
        if args.confirm != CONFIRMATION:
            raise SystemExit(
                f"Applying requires --confirm {CONFIRMATION} after reviewing the plan."
            )
        return apply_plan(load_plan(args.apply_plan))

    with connect() as connection:
        plan = build_plan(connection)
    print_plan(plan)
    if args.plan_out:
        args.plan_out.write_text(
            json.dumps(plan, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"Dry-run plan written to {args.plan_out}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
