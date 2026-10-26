from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from production_besten.api.app import create_app
from tests.integration.test_project_intake import intake, mutate
from tests.integration.scheduling_helpers import current_state


def test_create_customer_name_only_options_audit_and_state(engine, intake):
    case,api,_,_=intake
    state=current_state(engine,case)
    response=mutate(api,'POST','/customers',{'display_name':' Nico del Castillo '})
    assert response.status_code==201,response.text
    customer=response.json()['customer']
    assert customer=={'id':customer['id'],'display_name':'Nico del Castillo','phone':None,'email':None}
    assert customer['id'] in {c['id'] for c in api.get('/project-intake/options').json()['customers']}
    with engine.connect() as conn:
        audit=conn.execute(text("SELECT actor_user_id,entity_type,after_data FROM audit.audit_entries WHERE organization_id=:org AND entity_id=:id"),{'org':case.organization_id,'id':customer['id']}).one()
        assert audit.actor_user_id==case.actor_id and audit.entity_type=='customer'
        assert audit.after_data['customer']['id']==customer['id']
    assert current_state(engine,case)==state


@pytest.mark.parametrize('contacts',[{'phone':'','email':'  '},{'phone':' 12345 ','email':' nico@example.test '}])
def test_customer_optional_contacts(intake,contacts):
    _,api,_,_=intake
    response=mutate(api,'POST','/customers',{'display_name':'Cliente confirmado',**contacts})
    assert response.status_code==201,response.text
    customer=response.json()['customer']
    assert customer['phone']==(contacts['phone'].strip() or None)
    assert customer['email']==(contacts['email'].strip() or None)


@pytest.mark.parametrize('body',[{}, {'display_name':'   '},{'display_name':'x'*201},{'display_name':'Cliente','email':'invalid'},{'display_name':'Cliente','phone':'1'*81},{'display_name':'Cliente','organization_id':str(uuid4())}])
def test_customer_validation(intake,body):
    _,api,_,_=intake
    assert mutate(api,'POST','/customers',body).status_code==422


def test_customer_retry_and_intention_conflict(engine,intake):
    case,api,_,_=intake
    key=uuid4();body={'display_name':'Nico del Castillo'}
    first=mutate(api,'POST','/customers',body,key)
    replay=mutate(api,'POST','/customers',body,key)
    assert first.status_code==replay.status_code==201
    assert first.json()['customer']==replay.json()['customer'] and replay.json()['idempotent_replay']
    assert mutate(api,'POST','/customers',{'display_name':'Otro cliente'},key).status_code==409
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM core.customers WHERE organization_id=:org AND display_name='Nico del Castillo'"),{'org':case.organization_id})==1


def test_customer_concurrent_retry(intake):
    _,api,_,_=intake
    key=uuid4()
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses=list(pool.map(lambda _:mutate(api,'POST','/customers',{'display_name':'Cliente concurrente'},key),range(2)))
    assert all(r.status_code==201 for r in responses)
    assert responses[0].json()['customer']['id']==responses[1].json()['customer']['id']
    assert sorted(r.json()['idempotent_replay'] for r in responses)==[False,True]


def test_customer_name_is_not_unique(intake):
    _,api,_,_=intake
    responses=[mutate(api,'POST','/customers',{'display_name':'Mismo nombre'}) for _ in range(2)]
    assert all(r.status_code==201 for r in responses)
    assert responses[0].json()['customer']['id']!=responses[1].json()['customer']['id']


@pytest.mark.parametrize('scope',['tenant','plant','actor'])
def test_customer_context_isolation(engine,intake,scope):
    case,api,_,_=intake
    header={'tenant':'X-Dev-Organization-Id','plant':'X-Dev-Plant-Id','actor':'X-Dev-User-Id'}[scope]
    api.headers[header]=str(case.other_organization_id if scope=='tenant' else uuid4())
    assert mutate(api,'POST','/customers',{'display_name':'Must not exist'}).status_code==404
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM core.customers WHERE display_name='Must not exist'"))==0


def test_customer_options_do_not_leak_other_tenant(engine,intake):
    case,api,_,_=intake
    other=uuid4()
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO core.customers(id,organization_id,display_name) VALUES (:id,:org,'Cliente otro tenant')"),{'id':other,'org':case.other_organization_id})
    assert str(other) not in {c['id'] for c in api.get('/project-intake/options').json()['customers']}


def test_customer_transaction_rollback(engine,intake):
    case,api,_,_=intake
    broken=TestClient(create_app(engine=engine,enable_dev_context=True,failpoints={'project_intake':'after_intake'}),raise_server_exceptions=False)
    broken.headers.update(api.headers)
    assert mutate(broken,'POST','/customers',{'display_name':'Rollback customer'}).status_code==500
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM core.customers WHERE organization_id=:org AND display_name='Rollback customer'"),{'org':case.organization_id})==0
