"""Export persisted evaluation runs as portable PostgreSQL seed SQL."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import select

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from db import SessionLocal  # noqa: E402
from models import EvaluationRun  # noqa: E402


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _sql_value(value: object, column_name: str) -> str:
    if value is None:
        return "NULL"
    if column_name == "user_id":
        return "seed_user_id"
    if isinstance(value, (dict, list)):
        serialized = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        return f"{_sql_string(serialized)}::jsonb"
    if isinstance(value, UUID):
        return f"{_sql_string(str(value))}::uuid"
    if isinstance(value, datetime):
        return f"{_sql_string(value.isoformat())}::timestamptz"
    if isinstance(value, date):
        return f"{_sql_string(value.isoformat())}::date"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    return _sql_string(str(value))


def _render_sql(runs: list[EvaluationRun], target_user_id: int) -> str:
    columns = [column.name for column in EvaluationRun.__table__.columns]
    insert_columns = ",\n    ".join(f'"{name}"' for name in columns)
    mutable_columns = [name for name in columns if name != "id"]
    updates = ",\n        ".join(
        f'"{name}" = EXCLUDED."{name}"' for name in mutable_columns
    )

    statements = []
    for run in runs:
        values = ",\n    ".join(
            _sql_value(getattr(run, name), name) for name in columns
        )
        statements.append(
            "INSERT INTO evaluation_runs (\n    "
            f"{insert_columns}\n) VALUES (\n    {values}\n)\n"
            f"ON CONFLICT (id) DO UPDATE SET\n        {updates};"
        )

    return (
        "-- Generated from persisted KuKi evaluation_runs.\n"
        "-- Apply database migrations first. Set seed_user_id to an existing\n"
        "-- users.id in this database before running this file.\n"
        "BEGIN;\n"
        "DO $kuki_seed$\n"
        "DECLARE\n"
        f"    seed_user_id integer := {target_user_id};\n"
        "BEGIN\n"
        "    IF NOT EXISTS (SELECT 1 FROM users WHERE id = seed_user_id) THEN\n"
        "        RAISE EXCEPTION 'KuKi evaluation seed user id % does not exist', seed_user_id;\n"
        "    END IF;\n"
        + "\n\n".join("    " + statement.replace("\n", "\n    ") for statement in statements)
        + "\nEND\n"
        "$kuki_seed$;\n"
        "COMMIT;\n"
    )


async def _fetch_runs(run_ids: list[UUID], all_terminal: bool) -> list[EvaluationRun]:
    async with SessionLocal() as session:
        query = select(EvaluationRun)
        if run_ids:
            query = query.where(EvaluationRun.id.in_(run_ids)).order_by(
                EvaluationRun.created_at.asc()
            )
        elif all_terminal:
            query = (
                query.where(EvaluationRun.status.in_(["completed", "failed"]))
                .order_by(EvaluationRun.created_at.asc())
            )
        else:
            query = (
                query.where(EvaluationRun.status.in_(["completed", "failed"]))
                .order_by(EvaluationRun.created_at.desc())
                .limit(1)
            )

        runs = list((await session.scalars(query)).all())
        if run_ids:
            found_ids = {run.id for run in runs}
            missing_ids = [run_id for run_id in run_ids if run_id not in found_ids]
            if missing_ids:
                missing = ", ".join(str(run_id) for run_id in missing_ids)
                raise ValueError(f"Evaluation run(s) not found: {missing}")
        unfinished = [run.id for run in runs if run.status not in {"completed", "failed"}]
        if unfinished:
            ids = ", ".join(str(run_id) for run_id in unfinished)
            raise ValueError(
                f"Refusing to export unfinished evaluation run(s): {ids}. "
                "Wait for them to finish first."
            )
        return runs


async def _main() -> int:
    parser = argparse.ArgumentParser(
        description="Export evaluation run rows as PostgreSQL seed SQL."
    )
    parser.add_argument(
        "--run-id",
        action="append",
        type=UUID,
        default=[],
        help="Run UUID to export; repeat to export several runs.",
    )
    parser.add_argument(
        "--all-terminal",
        action="store_true",
        help="Export every completed or failed run instead of only the latest.",
    )
    parser.add_argument(
        "--target-user-id",
        type=int,
        default=1,
        help="Existing users.id to associate with the restored run(s) (default: 1).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Destination SQL file. Defaults to backend/evaluations/seeds/.",
    )
    args = parser.parse_args()
    if args.target_user_id < 1:
        parser.error("--target-user-id must be a positive integer")

    runs = await _fetch_runs(args.run_id, args.all_terminal)
    if not runs:
        print("No completed or failed evaluation runs found; no SQL file written.")
        return 1

    output = args.output
    if output is None:
        if len(runs) == 1:
            output = BACKEND_ROOT / "evaluations" / "seeds" / f"evaluation_run_{runs[0].id}.sql"
        else:
            output = BACKEND_ROOT / "evaluations" / "seeds" / "evaluation_runs.sql"
    if not output.is_absolute():
        output = Path.cwd() / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(_render_sql(runs, args.target_user_id), encoding="utf-8")

    print(f"Exported {len(runs)} evaluation run(s) to {output}")
    for run in runs:
        print(
            f"  {run.id} status={run.status} "
            f"cases={run.completed_count}/{run.case_count} "
            f"case_set={run.case_set_version}"
        )
    print(f"Restore association: users.id={args.target_user_id} (edit seed_user_id in SQL if needed).")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
