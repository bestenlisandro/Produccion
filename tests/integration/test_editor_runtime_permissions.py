"""Reproduce the pilot's runtime grants, rather than testing only as table owner."""
import os
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
from psycopg import sql
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url

from production_besten.api.app import create_app
from tests.integration.test_product_editor import editor, read, action
from tests.integration.test_project_intake import intake, mutate

SCHEMAS=('core','capacity','production','planning','execution','portal','integration','audit')


@pytest.fixture
def restricted_runtime(engine):
    url=make_url(os.environ['TEST_DATABASE_URL'])
    assert url.host=='127.0.0.1' and (url.database or '').startswith('besten_test_')
    role='besten_editor_runtime_'+uuid4().hex
    admin=psycopg.connect(host=url.host,port=url.port,user='postgres',dbname=url.database,autocommit=True)
    admin.execute(sql.SQL('CREATE ROLE {} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS').format(sql.Identifier(role)))
    runtime=None
    try:
        for schema in SCHEMAS:
            admin.execute(sql.SQL('GRANT USAGE ON SCHEMA {} TO {}').format(sql.Identifier(schema),sql.Identifier(role)))
            admin.execute(sql.SQL('GRANT SELECT ON ALL TABLES IN SCHEMA {} TO {}').format(sql.Identifier(schema),sql.Identifier(role)))
        for schema in ('core','capacity','production','planning','execution'):
            admin.execute(sql.SQL('GRANT INSERT,UPDATE ON ALL TABLES IN SCHEMA {} TO {}').format(sql.Identifier(schema),sql.Identifier(role)))
        for table in ('audit.audit_entries','integration.outbox_messages'):
            admin.execute(sql.SQL('GRANT INSERT ON TABLE {} TO {}').format(sql.Identifier(*table.split('.')),sql.Identifier(role)))
        runtime=create_engine(url.set(query={**url.query,'options':'-c role='+role}))

        def repair():
            source=(Path(__file__).resolve().parents[2]/'db/operations/editor_audit_result_permission.sql').read_text(encoding='utf-8')
            admin.execute(source.replace('produccion_besten_app',sql.Identifier(role).as_string(admin)))

        yield runtime,repair
    finally:
        if runtime:runtime.dispose()
        # This freshly created role owns no objects; remove only its disposable grants.
        admin.execute(sql.SQL('DROP OWNED BY {}').format(sql.Identifier(role)))
        admin.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))
        admin.close()


def incomplete_four_operations(engine,case,api,path,lot):
    project=UUID(path.split('/')[2])
    with engine.begin() as conn:
        conn.execute(text("UPDATE core.projects SET code='A685',name='Alacenas' WHERE id=:id"),{'id':project})
        definitions=[]
        for name in ('Corte / Escuadradora','Perforadora Múltiple','Armado','Instalación'):
            identifier=uuid4()
            conn.execute(text('INSERT INTO production.operation_definitions(id,organization_id,code,name,category) VALUES (:id,:org,:code,:name,:name)'),{'id':identifier,'org':case.organization_id,'code':'PILOT-'+identifier.hex,'name':name})
            definitions.append((identifier,name))
    lot={**lot,'name':'Alacenas','route_version_id':None,'operations':[]}
    for i,(identifier,name) in enumerate(definitions):
        lot['operations'].append({'code':f'OP-{i}','name':name,'operation_definition_id':str(identifier),'operation_kind':'installation' if i==3 else 'production','predecessor_codes':[] if i==0 else [f'OP-{i-1}'],'phases':[]})
    return {'expected_row_version':read(api,path)['row_version'],'lots':[lot]}


def snapshot(engine,org):
    tables=('core.projects','core.project_lots','production.required_operations','production.required_operation_phases','production.operation_precedences','planning.planning_state_heads','planning.planning_state_revisions','planning.effective_events','audit.audit_entries')
    with engine.connect() as conn:
        return {table:conn.execute(text('SELECT row_to_json(t)::text FROM '+table+' t WHERE organization_id=:org ORDER BY 1'),{'org':org}).scalars().all() for table in tables}


def test_missing_runtime_permission_rolls_back_then_same_request_succeeds(engine,editor,restricted_runtime):
    case,owner,path,lot=editor
    runtime,repair=restricted_runtime
    body=incomplete_four_operations(engine,case,owner,path,lot)
    before=snapshot(engine,case.organization_id)
    errors=[]
    def capture(context):errors.append((context.statement,getattr(context.original_exception,'sqlstate',None)))
    event.listen(runtime,'handle_error',capture)
    with TestClient(create_app(engine=runtime,enable_dev_context=True),raise_server_exceptions=False) as api:
        api.headers.update(owner.headers)
        key=uuid4()
        failed=mutate(api,'PUT',path,body,key)
        assert failed.status_code==500
        assert any('UPDATE audit.audit_entries SET after_data' in statement and state=='42501' for statement,state in errors)
        assert snapshot(engine,case.organization_id)==before

        repair()
        with runtime.connect() as conn:
            assert conn.execute(text("SELECT has_column_privilege(current_user,'audit.audit_entries','after_data','UPDATE'),has_column_privilege(current_user,'audit.audit_entries','metadata','UPDATE'),has_table_privilege(current_user,'audit.audit_entries','DELETE')")).one()==(True,False,False)
        saved=mutate(api,'PUT',path,body,key)
        assert saved.status_code==200,saved.text
        data=saved.json()
        assert len(data['lots'])==1 and len(data['lots'][0]['operations'])==4
        assert all(op['phases']==[] for op in data['lots'][0]['operations'])
        assert data['errors'] and data['status']=='draft'
        assert any('fase' in error for error in data['errors'])
        replay=mutate(api,'PUT',path,body,key)
        assert replay.status_code==200 and replay.json()['idempotent_replay']
        assert replay.json()['lots']==data['lots']
        validated=action(api,path,'validate')
        assert validated.status_code==200 and validated.json()['errors']
        frozen=action(api,path,'freeze')
        assert frozen.status_code==400 and 'fase' in frozen.json()['error']['message']
    with engine.connect() as conn:
        project=UUID(path.split('/')[2])
        assert conn.scalar(text('SELECT count(*) FROM core.project_lots WHERE project_id=:id'),{'id':project})==1
        assert conn.scalar(text('SELECT count(*) FROM production.required_operations WHERE project_id=:id'),{'id':project})==4


def test_restricted_runtime_draft_rollback_after_result_completion(engine,editor,restricted_runtime):
    case,owner,path,lot=editor
    runtime,repair=restricted_runtime
    repair()
    body=incomplete_four_operations(engine,case,owner,path,lot)
    before=snapshot(engine,case.organization_id)
    with TestClient(create_app(engine=runtime,enable_dev_context=True,failpoints={'product_editor':'after_editor'}),raise_server_exceptions=False) as api:
        api.headers.update(owner.headers)
        assert mutate(api,'PUT',path,body).status_code==500
    assert snapshot(engine,case.organization_id)==before
