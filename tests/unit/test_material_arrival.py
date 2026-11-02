from copy import deepcopy
from uuid import uuid4

import pytest

from production_besten.domain.errors import InvalidProductDefinition
from production_besten.domain.material_arrival import (
    build_template, catalog, terminals, validate_selection, STAGES,
)


def selection(case=3, materials=None, optional=None):
    return dict(route_code=f'MATERIAL_ROUTE_{case}', materials=materials or ['18','15','12','03','055'],
                optional_process_codes=optional or [])


def definitions():
    return [dict(id=uuid4(), code=code, status='active') for code in set(STAGES.values())]


def references(ops):
    return {o['code'].split('_',1)[1]: [p.split('_',1)[1] for p in o['predecessor_codes']] for o in ops}


@pytest.mark.parametrize('case,expected', [
    (1, {'COR-03':[], 'COR-055':[], 'MUL-18':[], 'SIN-18':[], 'ARM-01':['MUL-18','SIN-18','COR-03','COR-055']}),
    (2, {'MUL-18':[], 'SIN-18':[], 'ARM-01':['MUL-18','SIN-18']}),
    (3, {**{f'{kind}-{m}': ([] if kind=='COR' else [f'COR-{m}'] if kind=='PEG' else [f'PEG-{m}']) for m in ['18','15','12'] for kind in ['COR','PEG','MUL','SIN']}, 'COR-03':[], 'COR-055':[], 'ARM-01':['MUL-18','SIN-18','MUL-15','SIN-15','MUL-12','SIN-12','COR-03','COR-055']}),
    (4, {**{f'{kind}-{m}': ([] if kind=='PEG' else [f'PEG-{m}']) for m in ['18','15','12'] for kind in ['PEG','MUL','SIN']}, 'COR-03':[], 'COR-055':[], 'ARM-01':['MUL-18','SIN-18','MUL-15','SIN-15','MUL-12','SIN-12','COR-03','COR-055']}),
    (5, {'COR-15':[], 'PEG-15':['COR-15'], **{f'{kind}-{m}':(['PEG-15'] if m=='15' else []) for m in ['18','15','12'] for kind in ['MUL','SIN']}, 'COR-03':[], 'COR-055':[], 'ARM-01':['MUL-18','SIN-18','MUL-15','SIN-15','MUL-12','SIN-12','COR-03','COR-055']}),
])
def test_five_approved_route_fixtures(case, expected):
    actual=references(build_template(selection(case), definitions()))
    assert actual == expected
    assert not any(ref.startswith(('PEG-03','PEG-055','MUL-03','MUL-055')) for ref in actual)


@pytest.mark.parametrize('case,optional',[(1,['MUL-15','MUL-12','SIN-12','RAN-18','RAN-15']), (2,['MUL-15','RAN-18','RAN-15']), (3,['RAN-18']), (4,['RAN-18','RAN-15']), (5,['RAN-18','RAN-15'])])
def test_optional_active_terminal_branches(case,optional):
    graph=references(build_template(selection(case,optional=optional),definitions()))
    assert all(ref in graph['ARM-01'] for ref in optional)
    for ref in optional:
        assert graph[ref] == ([f'PEG-{ref.split("-")[1]}'] if case in [3,4] or case==5 and ref.endswith('-15') else [])


@pytest.mark.parametrize('count',[1,2,3])
def test_terminals_of_parallel_active_branches(count):
    ops=[dict(code='A',predecessor_codes=[])] + [dict(code=f'B{i}',predecessor_codes=['A']) for i in range(count)]
    assert terminals(ops)==[f'B{i}' for i in range(count)]


def test_terminals_single_chain_isolated_and_cycle():
    assert terminals([])==[]
    assert terminals([dict(code='A',predecessor_codes=[])])==['A']
    assert terminals([dict(code='A',predecessor_codes=[]),dict(code='B',predecessor_codes=['A'])])==['B']
    for ops in [[dict(code='A',predecessor_codes=['A'])], [dict(code='A',predecessor_codes=['B']),dict(code='B',predecessor_codes=['A'])], [dict(code='A',predecessor_codes=['X'])]]:
        with pytest.raises(InvalidProductDefinition):terminals(ops)


def test_inactive_optional_and_absent_materials_do_not_block_assembly():
    graph=references(build_template(selection(3,['03']),definitions()))
    assert graph=={'COR-03':[], 'ARM-01':['COR-03']}
    assert references(build_template(selection(2,['03']),definitions()))=={'ARM-01':[]}
    assert 'RAN-18' not in references(build_template(selection(),definitions()))


@pytest.mark.parametrize('case,optional',[(2,'MUL-12'),(3,'RAN-15'),(1,'SIN-15'),(5,'MUL-03')])
def test_matrix_no_cannot_be_selected(case,optional):
    with pytest.raises(InvalidProductDefinition):validate_selection(selection(case,optional=[optional]))


def test_catalog_and_missing_stage_are_explicit():
    assert [r['code'] for r in catalog()]==[f'MATERIAL_ROUTE_{i}' for i in range(1,6)]
    with pytest.raises(InvalidProductDefinition,match='Falta la etapa'):build_template(selection(),[])
    with pytest.raises(InvalidProductDefinition):validate_selection(selection(6))
    s=selection();s['materials']=['18','18']
    with pytest.raises(InvalidProductDefinition):validate_selection(s)


def test_no_transitive_redundant_edges_or_shared_concrete_ids():
    first=build_template(selection(5,optional=['RAN-15']),definitions())
    second=build_template(selection(5,optional=['RAN-15']),definitions())
    assert not set(o['code'] for o in first)&set(o['code'] for o in second)
    graph=references(first)
    assert graph['MUL-15']==graph['SIN-15']==graph['RAN-15']==['PEG-15']
    assert 'PEG-15' not in graph['ARM-01'] and 'COR-15' not in graph['ARM-01']


def test_templates_match_approved_repaired_workbook():
    """Independent source reconciliation of applicability and immediate edges."""
    from pathlib import Path
    from zipfile import ZipFile
    from xml.etree import ElementTree as E
    from production_besten.domain.material_arrival import PROCESSORS
    source=Path(__file__).resolve().parents[2]/'docs/Specs/Plantilla_Precedencias_Produccion_Besten_v5_REPARADA.xlsx'
    n={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with ZipFile(source) as z:
        strings=[''.join(t.itertext()) for t in E.fromstring(z.read('xl/sharedStrings.xml')).findall('s:si',n)] if 'xl/sharedStrings.xml' in z.namelist() else []
        wb=E.fromstring(z.read('xl/workbook.xml'))
        rels={r.attrib['Id']:r.attrib['Target'] for r in E.fromstring(z.read('xl/_rels/workbook.xml.rels'))}
        assert {'Matriz por caso','Casos de llegada','Instrucciones'} <= {s.attrib['name'] for s in wb.find('s:sheets',n)}
        sheet=next(s for s in wb.find('s:sheets',n) if s.attrib['name']=='Matriz por caso')
        target=rels[sheet.attrib['{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id']]
        target=target.lstrip('/') if target.startswith('/') else 'xl/'+target
        rows=[]
        for row in E.fromstring(z.read(target)).findall('.//s:sheetData/s:row',n):
            values={}
            for c in row:
                v=c.find('s:v',n);inline=c.find('s:is',n)
                value=v.text if v is not None else ''.join(inline.itertext()) if inline is not None else ''
                if c.attrib.get('t')=='s':value=strings[int(value)]
                values[''.join(ch for ch in c.attrib['r'] if ch.isalpha())]=value
            if values.get('A','').startswith(('COR-','PEG-','MUL-','SIN-','RAN-','ARM-')):rows.append(values)
    for case,(applies,preds) in enumerate(zip('FHJLN','GIKMO'),1):
        optional=[r['A'] for r in rows if r.get(applies)=='Según proyecto']
        graph=references(build_template(selection(case,optional=optional),definitions()))
        expected_active={r['A'] for r in rows if r.get(applies) in {'Sí','Según proyecto'}}
        assert set(graph)==expected_active
        for r in rows:
            ref=r['A']
            if ref in PROCESSORS:
                assert PROCESSORS[ref][case-1]=={'Sí':'yes','No':'no','Según proyecto':'optional'}[r[applies]]
            if ref in graph:
                assert set(graph[ref])==set(filter(None,r.get(preds,'').split(',')))
