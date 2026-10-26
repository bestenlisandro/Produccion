"""Installation projections over the existing operation/plan/execution model."""
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from sqlalchemy import text
from production_besten.domain.errors import EntityNotFound

LOCATION_FIELDS = ('installation_site_name', 'installation_address', 'installation_locality',
                   'installation_contact_name', 'installation_contact_phone', 'installation_access_notes')


def installation_overview(conn, org, plant, project=None):
    def rows(sql, **kw):
        return [dict(r) for r in conn.execute(text(sql), {'org': org, 'plant': plant, **kw}).mappings()]
    plants = rows('SELECT p.*,d.canonical_snapshot FROM core.plants p LEFT JOIN production.product_definition_revisions d ON d.organization_id=p.organization_id AND d.id=p.current_product_definition_revision_id WHERE p.organization_id=:org AND p.id=:plant')
    if not plants:
        raise EntityNotFound()
    snapshot = plants[0]['canonical_snapshot'] or {}
    projects = rows('SELECT p.*,c.display_name AS customer_name FROM core.projects p JOIN core.customers c ON c.organization_id=p.organization_id AND c.id=p.customer_id WHERE p.organization_id=:org AND p.plant_id=:plant')
    if project is not None and not any(p['id'] == project for p in projects):
        raise EntityNotFound()
    ops = rows('''SELECT o.*,l.code AS lot_code,e.id AS execution_id,e.status AS execution_status,e.started_at,e.completed_at,
        r.revision_no AS remaining_revision_no,r.remaining_labor_minutes,
        COALESCE((SELECT sum(s.work_minutes) FROM execution.execution_segments s WHERE s.organization_id=o.organization_id AND s.operation_execution_id=e.id AND s.segment_kind='work'),0) AS executed_minutes,
        (SELECT max(upper(s.time_range)) FROM execution.execution_segments s WHERE s.organization_id=o.organization_id AND s.operation_execution_id=e.id) AS last_segment_end,
        op.planned_start_at,op.planned_end_at,op.result_status
        FROM production.required_operations o JOIN core.projects p ON p.organization_id=o.organization_id AND p.id=o.project_id
        LEFT JOIN core.project_lots l ON l.organization_id=o.organization_id AND l.id=o.project_lot_id
        LEFT JOIN LATERAL (SELECT * FROM execution.operation_executions e WHERE e.organization_id=o.organization_id AND e.required_operation_id=o.id ORDER BY e.created_at DESC,e.id DESC LIMIT 1) e ON true
        LEFT JOIN execution.remaining_estimate_revisions r ON r.organization_id=o.organization_id AND r.operation_execution_id=e.id AND r.superseded_at IS NULL
        LEFT JOIN planning.plan_versions v ON v.organization_id=p.organization_id AND v.id=:plan
        LEFT JOIN planning.operation_plan_results op ON op.organization_id=o.organization_id AND op.required_operation_id=o.id AND op.schedule_solution_id=v.schedule_solution_id
        WHERE p.organization_id=:org AND p.plant_id=:plant''', plan=plants[0]['current_plan_version_id'])
    phases = rows('''SELECT ph.*,o.project_id FROM production.required_operation_phases ph JOIN production.required_operations o ON o.organization_id=ph.organization_id AND o.id=ph.required_operation_id JOIN core.projects p ON p.organization_id=o.organization_id AND p.id=o.project_id WHERE p.organization_id=:org AND p.plant_id=:plant ORDER BY ph.sequence_no''')
    people = rows('''SELECT DISTINCT pp.required_operation_phase_id,e.id,e.display_name AS name,h.time_range FROM planning.human_segment_assignments h JOIN planning.assignment_segments s ON s.organization_id=h.organization_id AND s.id=h.assignment_segment_id JOIN planning.planned_phase_assignments a ON a.organization_id=s.organization_id AND a.id=s.planned_phase_assignment_id JOIN planning.phase_plan_results pp ON pp.organization_id=a.organization_id AND pp.id=a.phase_plan_result_id JOIN planning.plan_versions v ON v.organization_id=pp.organization_id AND v.schedule_solution_id=pp.schedule_solution_id JOIN core.plants p ON p.organization_id=v.organization_id AND p.current_plan_version_id=v.id JOIN capacity.employees e ON e.organization_id=h.organization_id AND e.id=h.employee_id WHERE p.organization_id=:org AND p.id=:plant''')
    resources = rows('''SELECT DISTINCT pp.required_operation_phase_id,r.id,r.name FROM planning.physical_resource_reservations h JOIN planning.assignment_segments s ON s.organization_id=h.organization_id AND s.id=h.assignment_segment_id JOIN planning.planned_phase_assignments a ON a.organization_id=s.organization_id AND a.id=s.planned_phase_assignment_id JOIN planning.phase_plan_results pp ON pp.organization_id=a.organization_id AND pp.id=a.phase_plan_result_id JOIN planning.plan_versions v ON v.organization_id=pp.organization_id AND v.schedule_solution_id=pp.schedule_solution_id JOIN core.plants p ON p.organization_id=v.organization_id AND p.current_plan_version_id=v.id JOIN capacity.physical_resources r ON r.organization_id=h.organization_id AND r.id=h.physical_resource_id WHERE p.organization_id=:org AND p.id=:plant''')
    completed_phases = {r['entity_id'] for r in rows("SELECT DISTINCT e.entity_id FROM planning.effective_events e JOIN production.required_operation_phases ph ON ph.organization_id=e.organization_id AND ph.id=e.entity_id JOIN core.projects p ON p.organization_id=ph.organization_id JOIN production.required_operations o ON o.organization_id=ph.organization_id AND o.id=ph.required_operation_id AND o.project_id=p.id WHERE p.organization_id=:org AND p.plant_id=:plant AND e.event_type_code IN ('PHASE_COMPLETED','OPERATION_COMPLETED')")}
    from production_besten.persistence.production_release_uow import PostgresProductionReleaseUnitOfWork
    adapter = PostgresProductionReleaseUnitOfWork(None)
    adapter._connection = conn
    preparation = adapter.readiness(org, plant)
    results = []
    now = datetime.now(timezone.utc)
    for p in projects:
        if project is not None and p['id'] != project:
            continue
        definition = next((d for d in snapshot.get('projects', []) if d['code'] == p['code']), {})
        frozen_ops = [(l['code'], o) for l in definition.get('lots', []) for o in l.get('operations', [])]
        frozen_ops += [(None, o) for o in definition.get('unassigned_operations', [])]
        project_ops = [o for o in ops if o['project_id'] == p['id']]
        live = {(o['lot_code'], o['code']): o for o in project_ops}
        installations = []
        for lot, frozen in frozen_ops:
            if frozen.get('operation_kind') != 'installation':
                continue
            o = live.get((lot, frozen['code']))
            if not o:
                continue
            blockers = []
            if not (p['installation_address'] or '').strip(): blockers.append('Falta dirección de obra.')
            if not (p['installation_locality'] or '').strip(): blockers.append('Falta localidad de obra.')
            if not preparation[p['id']]['eligible']: blockers.append('Falta liberación productiva vigente y preparación válida.')
            needs = [r for ph in frozen.get('phases', []) for r in ph['labor_requirements'] if r['is_mandatory']]
            if not needs or any(not 1 <= r['min_people'] <= r['max_people'] <= 6 for r in needs): blockers.append('Se requiere un equipo válido de 1 a 6 personas.')
            pred_keys = {(e.get('predecessor_lot_code'),e['predecessor_code']) for e in frozen.get('predecessors',[])}
            predecessors = [live[k] for k in pred_keys if k in live]
            predecessors_complete = len(predecessors) == len(pred_keys) and all(v['execution_status'] == 'completed' for v in predecessors)
            op_phases = [ph for ph in phases if ph['required_operation_id'] == o['id'] and ph['status'] != 'archived']
            next_phase = next((ph for ph in op_phases if ph['id'] not in completed_phases), None)
            finished = o['execution_status'] == 'completed'
            state = 'finished' if finished else 'running' if o['execution_status'] in {'running','paused'} else 'blocked' if blockers else 'scheduled' if o['planned_start_at'] else 'ready' if predecessors_complete else 'not_ready'
            scheduled_dates=set()
            for r in people:
                if any(ph['id']==r['required_operation_phase_id'] for ph in op_phases):
                    day=r['time_range'].lower.astimezone(ZoneInfo(plants[0]['timezone'])).date()
                    last=(r['time_range'].upper-timedelta(microseconds=1)).astimezone(ZoneInfo(plants[0]['timezone'])).date()
                    while day<=last:
                        scheduled_dates.add(day.isoformat());day+=timedelta(days=1)
            installations.append({'scheduled_dates':sorted(scheduled_dates),'operation_id': o['id'], 'operation_name': o['name'], 'phase_id': next_phase['id'] if next_phase else None,
                'phase_name': next_phase['name'] if next_phase else None, 'execution_id': o['execution_id'], 'state': state,
                'ready_to_schedule': not blockers and not finished, 'ready_to_start': not blockers and predecessors_complete and not finished,
                'blockers': [] if finished else blockers + ([] if predecessors_complete else ['Producción precedente pendiente.']),
                'planned_start': o['planned_start_at'], 'planned_finish': o['planned_end_at'], 'started_at': o['started_at'], 'completed_at': o['completed_at'],
                'last_segment_end': o['last_segment_end'], 'duration_minutes': sum(ph['original_estimate_minutes'] for ph in frozen['phases']),
                'required_people': max((r['min_people'] for r in needs), default=0),
                'people': list({r['id']: {'id':r['id'],'name':r['name']} for r in people if any(ph['id']==r['required_operation_phase_id'] for ph in op_phases)}.values()),
                'resources': list({r['id']: {'id':r['id'],'name':r['name']} for r in resources if any(ph['id']==r['required_operation_phase_id'] for ph in op_phases)}.values()),
                'executed_minutes': o['executed_minutes'], 'remaining_minutes': 0 if finished else o['remaining_labor_minutes'],
                'remaining_revision_no': o['remaining_revision_no'], 'overdue': bool(not finished and o['planned_end_at'] and o['planned_end_at'] < now)})
        complete = bool(frozen_ops) and all((v:=live.get((lc,f['code']))) and v['execution_status']=='completed' for lc,f in frozen_ops)
        results.append({'project_id':p['id'],'project_code':p['code'],'project_name':p['name'],'customer_name':p['customer_name'],
                        'committed_date':p['committed_date'],'desired_start_at':p['desired_start_at'],'row_version':p['row_version'],'timezone':plants[0]['timezone'], 'required':bool(installations), 'can_complete':complete and p['status']!='archived',
                        'completed':complete and p['status']=='archived', **{k:p[k] for k in LOCATION_FIELDS},'installations':installations})
    return results


def project_completion(conn, org, plant, project):
    return installation_overview(conn, org, plant, project)[0]['can_complete']
