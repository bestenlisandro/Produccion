from copy import deepcopy
from uuid import UUID

import pytest
from sqlalchemy import text

from tests.integration.test_project_intake import intake
from tests.integration.test_product_editor import editor, read, save, action
from tests.unit.test_material_arrival import selection, references
from production_besten.domain.material_arrival import STAGES


def stages(engine,case):
    with engine.begin() as c:
        for index,code in enumerate(sorted(set(STAGES.values())),1):
            c.execute(text("INSERT INTO production.operation_definitions(organization_id,code,name,category,display_order) VALUES (:org,:code,:code,'production_stage',:n) ON CONFLICT (organization_id,code) DO NOTHING"),dict(org=case.organization_id,code=code,n=index))


@pytest.mark.parametrize('case_no',[1,2,3,4,5])
def test_routes_preview_save_reload_freeze_and_immutability(engine,editor,case_no):
    case,api,path,lot=editor
    stages(engine,case)
    catalog=api.get('/product-definition/material-arrival-routes')
    assert catalog.status_code==200 and len(catalog.json())==5
    options=selection(case_no)
    response=api.post('/product-definition/material-arrival-preview',json=options)
    assert response.status_code==200,response.text
    ops=response.json()
    assert read(api,path)['status']=='empty'  # Preview has no audit/write effects.
    for op in ops:
        op['phases']=[dict(code='WORK',name='Trabajo',original_estimate_minutes=15,required_people=1)]
    lot.update(route_version_id=None,material_arrival=options,operations=ops)
    response=save(api,path,[lot]);assert response.status_code==200,response.text
    persisted=read(api,path)
    assert persisted['lots'][0]['material_arrival']==options
    assert not persisted['errors'],persisted['errors']
    frozen=action(api,path,'freeze');assert frozen.status_code==200,frozen.text
    snapshot=frozen.json()['revisions'][0]['snapshot']['lots'][0]
    assert snapshot['material_arrival']==options
    before=deepcopy(snapshot)
    assert save(api,path,persisted['lots']).status_code==409
    assert read(api,path)['revisions'][0]['snapshot']['lots'][0]==before
    assert action(api,path,'new-revision').status_code==200
    current=read(api,path)
    current['lots'][0]['material_arrival']=selection(5)
    assert save(api,path,current['lots']).status_code==200
    assert read(api,path)['revisions'][0]['snapshot']['lots'][0]==before


def test_preview_errors_and_manual_graph_authority(engine,editor):
    case,api,path,lot=editor
    assert api.post('/product-definition/material-arrival-preview',json=selection()).status_code==400
    stages(engine,case)
    assert api.post('/product-definition/material-arrival-preview',json=selection(2,optional=['MUL-12'])).status_code==422
    lot['material_arrival']=selection(5)
    # Metadata does not impose a universal sequence on manually defined operations.
    assert save(api,path,[lot]).status_code==200
    persisted=read(api,path)['lots']
    assert persisted[0]['operations'][0]['predecessor_codes']==[]
    persisted[0]['operations'][0]['predecessor_codes']=['CUT']
    assert save(api,path,persisted).status_code==409


def test_m14_nullable_preservation_and_rollback(engine,editor):
    case,api,path,lot=editor
    with engine.connect() as c:
        before=c.scalar(text('SELECT material_arrival FROM core.project_lots WHERE id=:id'),dict(id=case.project_lot_id))
        assert before is None
        assert c.scalar(text("SELECT count(*) FROM information_schema.tables WHERE table_type='BASE TABLE' AND table_schema IN ('core','capacity','production','planning','execution','portal','integration','audit')"))==87
    from pathlib import Path
    root=Path(__file__).resolve().parents[2]
    with engine.connect() as c:
        transaction=c.begin()
        try:
            original=c.scalar(text("SELECT to_jsonb(l)-'material_arrival' FROM core.project_lots l WHERE id=:id"),dict(id=case.project_lot_id))
            for path in ['db/rollback/014_material_arrival.sql','db/migrations/014_material_arrival.sql']:
                c.exec_driver_sql((root/path).read_text(encoding='utf-8').replace('BEGIN;','').replace('COMMIT;',''))
            assert c.scalar(text("SELECT to_jsonb(l)-'material_arrival' FROM core.project_lots l WHERE id=:id"),dict(id=case.project_lot_id))==original
            assert c.scalar(text('SELECT material_arrival FROM core.project_lots WHERE id=:id'),dict(id=case.project_lot_id)) is None
        finally:
            transaction.rollback()


def test_selection_is_per_lot_and_new_codes_are_scoped(engine,editor):
    case,api,path,lot=editor
    stages(engine,case)
    lots=[]
    for n in [1,5]:
        l=deepcopy(lot);l['code']=f'LOT-{n}';l['route_version_id']=None;l['material_arrival']=selection(n)
        l['operations']=api.post('/product-definition/material-arrival-preview',json=selection(n)).json()
        for o in l['operations']:o['phases']=[dict(code='WORK',name='Trabajo',original_estimate_minutes=10)]
        lots.append(l)
    response=save(api,path,lots);assert response.status_code==200,response.text
    result=read(api,path)['lots']
    assert [l['material_arrival']['route_code'] for l in result]==['MATERIAL_ROUTE_1','MATERIAL_ROUTE_5']
    assert len({o['code'] for l in result for o in l['operations']})==sum(len(l['operations']) for l in result)
