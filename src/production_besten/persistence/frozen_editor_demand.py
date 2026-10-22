"""Resolve editor-managed demand from its immutable semantic snapshot.

Stable normalized identities remain available for execution and plan references,
including rows removed from the next draft. Legacy snapshots keep their loader.
"""
from datetime import datetime
from sqlalchemy import text


def frozen_editor_rows(conn, org, snapshot, projects, operations, phases, labor, physical):
    codes = set(snapshot.get('editor_frozen_projects', []))
    selected = {p['code']: p for p in projects if p['code'] in codes}
    if not selected:
        return operations, phases, labor, physical
    ids = [p['id'] for p in selected.values()]
    def rows(sql, **params):
        return [dict(r) for r in conn.execute(text(sql), {'org': org, **params}).mappings()]
    all_ops = rows('SELECT o.*,l.code AS lot_code,l.sequence_no AS lot_sequence FROM production.required_operations o LEFT JOIN core.project_lots l ON l.organization_id=o.organization_id AND l.id=o.project_lot_id WHERE o.organization_id=:org AND o.project_id=ANY(:ids)', ids=ids)
    op_by = {(o['project_id'], o['lot_code'], o['code']): o for o in all_ops}
    all_phases = rows('SELECT ph.* FROM production.required_operation_phases ph JOIN production.required_operations o ON o.organization_id=ph.organization_id AND o.id=ph.required_operation_id WHERE o.organization_id=:org AND o.project_id=ANY(:ids)', ids=ids)
    phase_by = {(p['required_operation_id'], p['code']): p for p in all_phases}
    catalogs = {}
    for key, table in [('skill','capacity.skills'),('center','capacity.work_centers'),('type','capacity.physical_resource_types'),('group','capacity.physical_resource_groups')]:
        catalogs[key] = {r['code']: r['id'] for r in rows(f'SELECT id,code FROM {table} WHERE organization_id=:org')}
    req_ids = rows('SELECT r.id,r.required_operation_phase_id FROM production.operation_physical_requirements r JOIN production.required_operation_phases ph ON ph.organization_id=r.organization_id AND ph.id=r.required_operation_phase_id JOIN production.required_operations o ON o.organization_id=ph.organization_id AND o.id=ph.required_operation_id WHERE o.organization_id=:org AND o.project_id=ANY(:ids) ORDER BY r.created_at,r.id', ids=ids)
    removed_phases = {p['id'] for p in all_phases}
    operations = [o for o in operations if o['project_id'] not in ids]
    phases = [p for p in phases if p['project_id'] not in ids]
    labor = [r for r in labor if r['required_operation_phase_id'] not in removed_phases]
    physical = [r for r in physical if r['required_operation_phase_id'] not in removed_phases]
    def instant(value):
        return datetime.fromisoformat(value.replace('Z', '+00:00')) if value else None
    for project in snapshot.get('projects', []):
        if project['code'] not in selected:
            continue
        project_id = selected[project['code']]['id']
        groups = [(None, project.get('unassigned_operations', []))] + [(lot, lot['operations']) for lot in project.get('lots', [])]
        for lot, ops in groups:
            for op in ops:
                row = dict(op_by[(project_id, lot['code'] if lot else None, op['code'])])
                row['settings'] = op['settings']
                row['earliest_start_at'] = instant(op['earliest_start_at'])
                operations.append(row)
                for ph in op['phases']:
                    original = phase_by[(row['id'], ph['code'])]
                    phase = {**original, **{k: ph[k] for k in ('sequence_no', 'code', 'name', 'estimate_kind', 'original_estimate_minutes', 'split_policy')}}
                    phase.update(project_id=project_id, project_code=project['code'], project_lot_id=row['project_lot_id'], lot_code=row['lot_code'], lot_sequence=lot['sequence_no'] if lot else 32767, operation_code=op['code'], settings=op['settings'], operation_earliest=row['earliest_start_at'], earliest_start_at=instant(ph['earliest_start_at']))
                    phases.append(phase)
                    for req in ph['labor_requirements']:
                        if req['is_mandatory']:
                            labor.append({**req, 'required_operation_phase_id': phase['id'], 'skill_id': catalogs['skill'][req['code']]})
                    source = [r['id'] for r in req_ids if r['required_operation_phase_id'] == phase['id']]
                    for i, req in enumerate(ph['physical_requirements']):
                        if req['is_mandatory']:
                            physical.append({**req, 'id': source[i], 'required_operation_phase_id': phase['id'], 'physical_resource_type_id': catalogs['type'].get(req['resource_type_code']), 'physical_resource_group_id': catalogs['group'].get(req['resource_group_code']), 'work_center_id': catalogs['center'].get(req['work_center_code'])})
    return operations, phases, labor, physical


def frozen_editor_precedences(snapshot, projects, operations, existing):
    codes = set(snapshot.get('editor_frozen_projects', []))
    managed = {p['id']: p['code'] for p in projects if p['code'] in codes}
    op_map = {(o['project_id'], o['lot_code'], o['code']): o['id'] for o in operations}
    op_ids = {o['id'] for o in operations if o['project_id'] in managed}
    result = [r for r in existing if r['successor_operation_id'] not in op_ids]
    project_map = {v: k for k, v in managed.items()}
    for p in snapshot.get('projects', []):
        if p['code'] not in project_map:
            continue
        pid = project_map[p['code']]
        for lot in p.get('lots', []):
            for o in lot['operations']:
                for edge in o['predecessors']:
                    predecessor = op_map.get((pid, edge['predecessor_lot_code'], edge['predecessor_code']))
                    successor = op_map.get((pid, lot['code'], o['code']))
                    if predecessor and successor:
                        result.append({'predecessor_operation_id': predecessor, 'successor_operation_id': successor, 'precedence_type': edge['precedence_type'], 'lag_minutes': edge['lag_minutes']})
    return result
