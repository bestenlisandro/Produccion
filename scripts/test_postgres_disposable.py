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
                if migration.name.startswith('011_'):
                    upgrade_ids = tuple(uuid4() for _ in range(6))
                    org, plant, customer, priority, project, calendar = upgrade_ids
                    with conn.transaction():
                        conn.execute("INSERT INTO core.organizations(id,slug,legal_name,display_name,default_timezone) VALUES (%s,%s,'Upgrade fixture','Upgrade fixture','UTC')", (org,'upgrade-'+org.hex))
                        conn.execute("INSERT INTO capacity.calendars(id,organization_id,code,name,timezone,calendar_kind) VALUES (%s,%s,'UPGRADE','Upgrade fixture','UTC','plant')",(calendar,org))
                        conn.execute("INSERT INTO core.plants(id,organization_id,code,name,timezone,base_calendar_id) VALUES (%s,%s,'UPGRADE','Upgrade fixture','UTC',%s)", (plant,org,calendar))
                        conn.execute("INSERT INTO core.customers(id,organization_id,display_name) VALUES (%s,%s,'Historical customer')", (customer,org))
                        conn.execute("INSERT INTO core.project_priorities(id,organization_id,code,name,rank) VALUES (%s,%s,'NORMAL','Normal',1)", (priority,org))
                        conn.execute("INSERT INTO core.projects(id,organization_id,plant_id,customer_id,priority_id,code,name,description) VALUES (%s,%s,%s,%s,%s,'HISTORIC','Historical project','Preserved by M11')", (project,org,plant,customer,priority))
                conn.execute(migration.read_text(encoding="utf-8"))
                if migration.name.startswith('011_'):
                    row=conn.execute("SELECT description,installation_site_name,installation_address,installation_locality,installation_contact_name,installation_contact_phone,installation_access_notes FROM core.projects WHERE id=%s",(project,)).fetchone()
                    assert row == ('Preserved by M11',None,None,None,None,None,None), row
                    with conn.transaction():
                        for table, ident in [('core.projects',project),('core.customers',customer),('core.project_priorities',priority),('core.plants',plant),('capacity.calendars',calendar),('core.organizations',org)]:
                            conn.execute(sql.SQL('DELETE FROM {} WHERE id=%s').format(sql.Identifier(*table.split('.'))),(ident,))
                    print('M10 -> M11: historical project preserved; six nullable fields remain NULL.', flush=True)
            counts = conn.execute("""SELECT count(DISTINCT table_schema),count(*)
                FROM information_schema.tables WHERE table_type='BASE TABLE'
                AND table_schema IN ('core','capacity','production','planning',
                'execution','portal','integration','audit')""").fetchone()
            assert counts == (8, 87), counts
            print("M0-M11 applied: 8 schemas / 87 tables", flush=True)
            for verification in ('verify_schema.sql','temporal_scenarios.sql'):
                source=(root / 'db/verify' / verification).read_text(encoding='utf-8')
                source='\n'.join(line for line in source.splitlines() if not line.startswith('\\set '))
                conn.execute(source)
                print(verification + ': passed (rolled back)', flush=True)
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
