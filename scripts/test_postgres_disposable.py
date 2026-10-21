"""Run tests in an isolated PostgreSQL 18 database; always remove owned objects.

Uses libpq's existing administrative credential without inspecting its file.
The effective test role is NOLOGIN and owns only the random disposable database.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4
from urllib.parse import urlencode

import psycopg
from psycopg import sql


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    name = "besten_test_" + uuid4().hex
    admin = psycopg.connect(host="127.0.0.1", port=5432, user="postgres",
                             dbname="postgres", autocommit=True)
    role_created = database_created = False
    try:
        admin.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(name)))
        role_created = True
        admin.execute(sql.SQL("CREATE DATABASE {} OWNER {}").format(
            sql.Identifier(name), sql.Identifier(name)))
        database_created = True
        with psycopg.connect(host="127.0.0.1", port=5432, user="postgres",
                              dbname=name, options=f"-c role={name}", autocommit=True) as conn:
            for migration in sorted((root / "db/migrations").glob("*.sql")):
                conn.execute(migration.read_text(encoding="utf-8"))
            counts = conn.execute("""SELECT count(DISTINCT table_schema),count(*)
                FROM information_schema.tables WHERE table_type='BASE TABLE'
                AND table_schema IN ('core','capacity','production','planning',
                'execution','portal','integration','audit')""").fetchone()
            assert counts == (8, 87), counts
            print("M0-M10 applied: 8 schemas / 87 tables", flush=True)
        environment = os.environ.copy()
        environment.pop("PGPASSWORD", None)
        environment["TEST_DATABASE_URL"] = (
            f"postgresql+psycopg://postgres@127.0.0.1:5432/{name}?"
            + urlencode({"options": f"-c role={name}"}))
        return subprocess.call([sys.executable, "-m", "pytest", *sys.argv[1:]],
                               cwd=root, env=environment)
    finally:
        if database_created:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
        if role_created:
            admin.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(name)))
        admin.close()
        print("Disposable database and role removed; connection variables were child-only.", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
