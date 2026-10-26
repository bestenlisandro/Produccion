"""Real browser -> Vite -> FastAPI -> disposable PostgreSQL customer smoke.

Run only through: python scripts/test_postgres_disposable.py --customer-ui-smoke
Never connects to the persistent pilot database.
"""
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import time
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
import uvicorn

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from production_besten.api.app import create_app


def main():
    url=make_url(os.environ['TEST_DATABASE_URL'])
    if (url.host!='127.0.0.1' or url.username!='postgres'
        or not (url.database or '').startswith('besten_test_')
        or url.query.get('options')!='-c role='+url.database):
        raise RuntimeError('Customer UI smoke requires the owned disposable database/role.')
    node=shutil.which('node')
    if not node:raise RuntimeError('Node is required for the browser smoke.')
    engine=create_engine(url)
    server=None;thread=None
    try:
        org,calendar,plant,actor,priority=tuple(uuid4() for _ in range(5))
        with engine.begin() as conn:
            assert conn.scalar(text('SELECT count(*) FROM core.organizations'))==0
            params={'org':org,'cal':calendar,'plant':plant,'actor':actor,'priority':priority}
            conn.execute(text("INSERT INTO core.organizations(id,slug,legal_name,display_name,default_timezone) VALUES (:org,'customer-ui-smoke','Disposable UI','Disposable UI','UTC')"),params)
            conn.execute(text("INSERT INTO capacity.calendars(id,organization_id,code,name,timezone,calendar_kind) VALUES (:cal,:org,'BASE','Disposable calendar','UTC','plant')"),params)
            conn.execute(text("INSERT INTO core.plants(id,organization_id,code,name,timezone,base_calendar_id) VALUES (:plant,:org,'UI','Disposable plant','UTC',:cal)"),params)
            conn.execute(text("INSERT INTO core.user_profiles(id,organization_id,auth_subject,display_name) VALUES (:actor,:org,'disposable-customer-ui','Disposable actor')"),params)
            conn.execute(text("INSERT INTO core.project_priorities(id,organization_id,code,name,rank) VALUES (:priority,:org,'NORMAL','NORMAL',3)"),params)
        listener=socket.socket()
        listener.bind(('127.0.0.1',0))
        api_port=listener.getsockname()[1]
        server=uvicorn.Server(uvicorn.Config(create_app(engine=engine,enable_dev_context=True),log_level='warning'))
        thread=threading.Thread(target=server.run,kwargs={'sockets':[listener]},daemon=True)
        thread.start()
        deadline=time.monotonic()+15
        while not server.started:
            if not thread.is_alive() or time.monotonic()>deadline:raise RuntimeError('Disposable API did not start.')
            time.sleep(.05)
        env=os.environ.copy()
        env.update(DATABASE_URL=str(url),VITE_DEV_ORGANIZATION_ID=str(org),VITE_DEV_PLANT_ID=str(plant),VITE_DEV_USER_ID=str(actor),CUSTOMER_SMOKE_API=f'http://127.0.0.1:{api_port}')
        subprocess.run([node,'scripts/customer-ui-live.mjs'],cwd=ROOT/'frontend',env=env,check=True,timeout=90)
        with engine.connect() as conn:
            customer=conn.execute(text('SELECT display_name,phone,email FROM core.customers')).one()
            assert tuple(customer)==('Cliente E2E descartable',None,None)
            assert conn.scalar(text('SELECT count(*) FROM core.projects'))==0
            assert conn.scalar(text('SELECT count(*) FROM audit.audit_entries'))==1
        print('REAL_CUSTOMER_UI_SMOKE passed: actual customer persisted once; project A685 stayed unsaved.',flush=True)
    finally:
        if server:server.should_exit=True
        if thread:
            thread.join(timeout=15)
            if thread.is_alive():raise RuntimeError('Disposable API did not stop.')
        engine.dispose()


if __name__=='__main__':main()
