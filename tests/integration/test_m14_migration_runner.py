"""Exercise the official incremental runner only against an owned test DB."""
from pathlib import Path
import shutil
import subprocess

from sqlalchemy import text


def test_m14_official_runner_and_duplicate_guard(engine, seeded_case):
    assert engine.url.database.startswith('besten_test_')
    root = Path(__file__).resolve().parents[2]
    shell = shutil.which('pwsh') or shutil.which('powershell')
    psql = shutil.which('psql') or r'C:\Program Files\PostgreSQL\18\bin\psql.exe'
    assert shell and Path(psql).is_file()
    with engine.begin() as conn:
        original = conn.scalar(text("SELECT to_jsonb(l)-'material_arrival' FROM core.project_lots l WHERE id=:id"), {'id': seeded_case.project_lot_id})
        conn.exec_driver_sql((root/'db/rollback/014_material_arrival.sql').read_text().replace('BEGIN;', '').replace('COMMIT;', ''))
    connection = f"host=127.0.0.1 port=5432 user=postgres dbname={engine.url.database} options='-c role={engine.url.database}'"
    command = [shell, '-NoProfile', '-File', str(root/'db/verify/apply_with_psql.ps1'),
               '-DatabaseUrl', connection, '-PsqlPath', psql, '-FromMigration', '14', '-SchemaOnly']
    result = subprocess.run(command, cwd=root, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'Applying 014_material_arrival.sql' in result.stdout
    assert 'Applying 013_' not in result.stdout and 'temporal_scenarios.sql' not in result.stdout
    duplicate = subprocess.run(command, cwd=root, capture_output=True, text=True)
    assert duplicate.returncode != 0
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT to_jsonb(l)-'material_arrival' FROM core.project_lots l WHERE id=:id"), {'id': seeded_case.project_lot_id}) == original
        assert conn.scalar(text('SELECT material_arrival FROM core.project_lots WHERE id=:id'), {'id': seeded_case.project_lot_id}) is None
