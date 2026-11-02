"""Initial templates transcribed from v5_REPARADA, never scheduler rules.

Functional references are distinct from concrete operation codes and database IDs.
Ranurado uses the existing Corte stage (escuadradora), not a new stage/catalog row.
"""
from uuid import uuid4

from production_besten.domain.errors import InvalidProductDefinition
from production_besten.domain.precedence import has_cycle


MATERIALS = ('18', '15', '12', '03', '055')
LABELS = {'18': '18 mm', '15': '15 mm', '12': '12 mm', '03': 'Fondo 3 mm', '055': 'Fondo 5,5 mm'}
ROUTES = (
    ('Todo cortado y pegado; fondos 3 mm y 5,5 mm enteros', 'Melaminas listas para procesados. Fondos: Corte independiente.'),
    ('Todo cortado y pegado; fondos 3 mm y 5,5 mm cortados', 'Sin Corte ni Pegado internos. Procesados aplicables → Armado.'),
    ('Tableros enteros', 'Melaminas: Corte → Pegado → procesados. Fondos: Corte independiente.'),
    ('Melaminas cortadas sin pegado; fondos 3 mm y 5,5 mm enteros', 'Melaminas: Pegado → procesados. Sin Corte de melamina. Fondos: Corte independiente.'),
    ('Todo cortado y pegado, excepto melamina 15 mm y fondos enteros', '18/12 mm listas. 15 mm: Corte → Pegado → procesados. Fondos: Corte independiente.'),
)
# Five columns are cases 1..5, matching Matriz por caso F/H/J/L/N.
# yes = suggested by the approved matrix; optional = explicit project choice.
PROCESSORS = {
    'MUL-18': ('yes', 'yes', 'yes', 'yes', 'yes'),
    'MUL-15': ('optional', 'optional', 'yes', 'yes', 'yes'),
    'MUL-12': ('optional', 'no', 'yes', 'yes', 'yes'),
    'SIN-18': ('yes', 'yes', 'yes', 'yes', 'yes'),
    'SIN-15': ('no', 'no', 'yes', 'yes', 'yes'),
    'SIN-12': ('optional', 'no', 'yes', 'yes', 'yes'),
    'RAN-18': ('optional', 'optional', 'optional', 'optional', 'optional'),
    'RAN-15': ('optional', 'optional', 'no', 'optional', 'optional'),
}
STAGES = {'COR': 'CORTE_ESCUADRADORA', 'PEG': 'PEGADO', 'MUL': 'PERFORADORA_MULTIPLE', 'SIN': 'PROCESADO_SIN_MULTIPLE', 'RAN': 'CORTE_ESCUADRADORA', 'ARM': 'ARMADO'}
NAMES = {'COR': 'Corte', 'PEG': 'Pegado de cantos', 'MUL': 'Múltiple', 'SIN': 'Procesado sin Múltiple', 'RAN': 'Ranurado', 'ARM': 'Armado'}


def route_index(code):
    codes = [f'MATERIAL_ROUTE_{i}' for i in range(1, 6)]
    if code not in codes:
        raise InvalidProductDefinition('Ruta de llegada de material inexistente.')
    return codes.index(code)


def validate_selection(selection):
    index = route_index(selection['route_code'])
    materials = selection['materials']
    optional = selection['optional_process_codes']
    if len(materials) != len(set(materials)) or not set(materials) <= set(MATERIALS) or not materials:
        raise InvalidProductDefinition('Seleccioná materiales válidos sin repetir.')
    if len(optional) != len(set(optional)):
        raise InvalidProductDefinition('Procesados opcionales repetidos.')
    for ref in optional:
        if ref not in PROCESSORS or PROCESSORS[ref][index] != 'optional' or ref.split('-')[1] not in materials:
            raise InvalidProductDefinition('Procesado opcional no aplicable a la ruta o al material.')


def catalog():
    return [dict(code=f'MATERIAL_ROUTE_{i+1}', name=f'Caso {i+1} — {name}', summary=summary,
                 processors=[dict(reference=ref, material=ref.split('-')[1], name=NAMES[ref[:3]], applicability=values[i]) for ref, values in PROCESSORS.items()])
            for i, (name, summary) in enumerate(ROUTES)]


def terminals(operations):
    """Validate the active DAG and return only nodes with no active successor."""
    codes = [o['code'] for o in operations]
    if len(codes) != len(set(codes)):
        raise InvalidProductDefinition('Códigos de operación repetidos.')
    edges = [(p, o['code']) for o in operations for p in o['predecessor_codes']]
    if any(p not in codes for p, _ in edges) or has_cycle(edges):
        raise InvalidProductDefinition('Las precedencias contienen un ciclo o una referencia inexistente.')
    parents = {p for p, _ in edges}
    return [code for code in codes if code not in parents]


def build_template(selection, definitions):
    validate_selection(selection)
    case = route_index(selection['route_code']) + 1
    definitions = {o['code']: o['id'] for o in definitions if o.get('status', 'active') == 'active'}
    prefix = uuid4().hex[:12]
    operations = []
    references = {}

    def add(ref, predecessors=()):
        kind, material = ref.split('-')
        stage = STAGES[kind]
        if stage not in definitions:
            raise InvalidProductDefinition(f'Falta la etapa activa {stage}. No se puede generar la ruta.')
        code = prefix + '_' + ref
        references[ref] = code
        operations.append(dict(code=code, name=NAMES[kind] + (f' · {LABELS[material]}' if kind != 'ARM' else ''),
                               operation_definition_id=definitions[stage], operation_kind='production',
                               predecessor_codes=[references[p] for p in predecessors], phases=[]))

    for material in MATERIALS:
        if material not in selection['materials']:
            continue
        if material in ('03', '055'):
            if case != 2:
                add('COR-' + material)
            continue
        whole = case == 3 or (case == 5 and material == '15')
        glue = whole or case == 4
        if whole:
            add('COR-' + material)
        if glue:
            add('PEG-' + material, ['COR-' + material] if whole else [])
        for ref, applicability in PROCESSORS.items():
            if ref.split('-')[1] != material:
                continue
            if applicability[case-1] == 'yes' or ref in selection['optional_process_codes']:
                add(ref, ['PEG-' + material] if glue else [])
    active_terminals = terminals(operations)
    add('ARM-01')
    operations[-1]['predecessor_codes'] = active_terminals
    terminals(operations)  # Same cycle validator as manual editor/precedence writes.
    return operations
