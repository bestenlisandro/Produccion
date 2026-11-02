"""Actual Playwright -> Vite -> API -> disposable PostgreSQL; no HTTP mocks."""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import threading
import time
from uuid import uuid4

from sqlalchemy import text
import uvicorn

from production_besten.api.app import create_app
from tests.integration.test_material_arrival import stages


def test_material_routes_real_browser(engine,seeded_case):
    case=seeded_case
    assert engine.url.database.startswith('besten_test_'), 'Disposable DB required'
    stages(engine,case)
    projects=[]
    with engine.begin() as c:
        current=c.scalar(text('SELECT current_plan_version_id FROM core.plants WHERE id=:id'),dict(id=case.plant_id))
        for width in [1440,1366,1024,390]:
            for route in [3,5]:
                project=uuid4()
                c.execute(text("INSERT INTO core.projects(id,organization_id,plant_id,customer_id,priority_id,code,name,status) SELECT :id,organization_id,plant_id,customer_id,priority_id,:code,'Disposable material route','active' FROM core.projects WHERE id=:original"),dict(id=project,original=case.project_id,code=f'ROUTE-{width}-{route}'))
                projects.append(dict(id=str(project),width=width,route=route))
    listener=socket.socket();listener.bind(('127.0.0.1',0))
    port=listener.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(create_app(engine=engine,enable_dev_context=True),log_level='warning'))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[listener]},daemon=True)
    root=Path(__file__).resolve().parents[2]
    thread.start()
    try:
        deadline=time.monotonic()+15
        while not server.started:
            if not thread.is_alive() or time.monotonic()>deadline:raise RuntimeError('API did not start')
            time.sleep(.05)
        env=os.environ.copy()
        env.update(VITE_DEV_ORGANIZATION_ID=str(case.organization_id),VITE_DEV_PLANT_ID=str(case.plant_id),VITE_DEV_USER_ID=str(case.actor_id),MATERIAL_ROUTES_API=f'http://127.0.0.1:{port}',MATERIAL_ROUTES_PROJECTS=json.dumps(projects))
        subprocess.run([shutil.which('node'),'scripts/material-arrival-ui-live.mjs'],cwd=root/'frontend',env=env,check=True,timeout=240)
        with engine.connect() as c:
            assert c.scalar(text('SELECT current_plan_version_id FROM core.plants WHERE id=:id'),dict(id=case.plant_id))==current
            assert c.scalar(text('SELECT count(*) FROM planning.scenarios WHERE organization_id=:org'),dict(org=case.organization_id))==1
            assert c.scalar(text('SELECT count(*) FROM execution.operation_executions WHERE organization_id=:org'),dict(org=case.organization_id))==1
    finally:
        server.should_exit=True;thread.join(timeout=15)
        assert not thread.is_alive()
