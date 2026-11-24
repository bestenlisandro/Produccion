"""Tenant/plant scoped execution detail, independent of the published plan."""
from sqlalchemy import text

from production_besten.domain.errors import EntityNotFound


def operation_execution(conn, org, plant, operation_id, *, can_execute):
    params = {'org': org, 'plant': plant, 'operation': operation_id}
    operation = conn.execute(text("""
        SELECT o.id, p.status AS project_status, o.status, pl.timezone,
               pl.current_product_definition_revision_id,
               e.id AS execution_id,e.status AS execution_status,e.started_at,e.completed_at,
               r.revision_no AS remaining_revision_no,r.remaining_labor_minutes AS remaining_minutes
        FROM production.required_operations o
        JOIN core.projects p ON p.organization_id=o.organization_id AND p.id=o.project_id
        JOIN core.plants pl ON pl.organization_id=p.organization_id AND pl.id=p.plant_id
        LEFT JOIN LATERAL (SELECT * FROM execution.operation_executions x
          WHERE x.organization_id=o.organization_id AND x.required_operation_id=o.id
          ORDER BY x.started_at DESC,x.created_at DESC LIMIT 1) e ON true
        LEFT JOIN execution.remaining_estimate_revisions r ON r.organization_id=e.organization_id
          AND r.operation_execution_id=e.id AND r.superseded_at IS NULL
        WHERE o.organization_id=:org AND o.id=:operation AND p.plant_id=:plant
    """), params).mappings().one_or_none()
    if operation is None:
        raise EntityNotFound('Operación fuera de la planta seleccionada.')
    params['execution'] = operation['execution_id']
    phases = [dict(r) for r in conn.execute(text("""
        SELECT ph.id,ph.name,ph.original_estimate_minutes,
          GREATEST(ph.required_people,COALESCE((SELECT max(l.min_people) FROM production.operation_labor_requirements l
            WHERE l.organization_id=ph.organization_id AND l.required_operation_phase_id=ph.id AND l.is_mandatory),0)) AS required_people,
          EXISTS(SELECT 1 FROM planning.effective_events e WHERE e.organization_id=ph.organization_id
            AND e.payload->>'operation_execution_id'=CAST(:execution AS text)
            AND e.payload->>'phase_id'=ph.id::text
            AND e.event_type_code IN ('OPERATION_STARTED','PHASE_STARTED')) AS started,
          EXISTS(SELECT 1 FROM planning.effective_events e WHERE e.organization_id=ph.organization_id
            AND e.payload->>'operation_execution_id'=CAST(:execution AS text)
            AND e.entity_id=ph.id AND e.event_type_code IN ('PHASE_COMPLETED','OPERATION_COMPLETED')) AS completed
        FROM production.required_operation_phases ph
        WHERE ph.organization_id=:org AND ph.required_operation_id=:operation AND ph.status<>'archived'
        ORDER BY ph.sequence_no,ph.id
    """), params).mappings()]
    segments = [dict(r) for r in conn.execute(text("""
        SELECT s.id,s.required_operation_phase_id AS phase_id,ph.name AS phase_name,
               lower(s.time_range) AS started_at,upper(s.time_range) AS ended_at,s.work_minutes,
               COALESCE((SELECT jsonb_agg(jsonb_build_object('id',u.employee_id,'name',e.display_name,'minutes',u.work_minutes))
                 FROM execution.actual_resource_usages u JOIN capacity.employees e ON e.organization_id=u.organization_id AND e.id=u.employee_id
                 WHERE u.organization_id=s.organization_id AND u.execution_segment_id=s.id
                   AND NOT EXISTS(SELECT 1 FROM execution.actual_resource_usages n WHERE n.organization_id=u.organization_id AND n.supersedes_id=u.id)), '[]') AS people,
               COALESCE((SELECT jsonb_agg(jsonb_build_object('id',u.physical_resource_id,'name',r.name,'minutes',u.work_minutes))
                 FROM execution.actual_resource_usages u JOIN capacity.physical_resources r ON r.organization_id=u.organization_id AND r.id=u.physical_resource_id
                 WHERE u.organization_id=s.organization_id AND u.execution_segment_id=s.id
                   AND NOT EXISTS(SELECT 1 FROM execution.actual_resource_usages n WHERE n.organization_id=u.organization_id AND n.supersedes_id=u.id)), '[]') AS resources
        FROM execution.execution_segments s
        JOIN production.required_operation_phases ph ON ph.organization_id=s.organization_id AND ph.id=s.required_operation_phase_id
        WHERE s.organization_id=:org AND s.operation_execution_id=:execution
          AND NOT EXISTS(SELECT 1 FROM execution.execution_segments n WHERE n.organization_id=s.organization_id AND n.supersedes_id=s.id)
        ORDER BY lower(s.time_range),s.segment_no
    """), params).mappings()]
    choices = {}
    for key, table in [('people', 'employees'), ('resources', 'physical_resources')]:
        name_column = 'display_name' if table == 'employees' else 'name'
        choices[key] = [dict(r) for r in conn.execute(text(f"SELECT id,{name_column} AS name FROM capacity.{table} WHERE organization_id=:org AND plant_id=:plant AND status='active' ORDER BY name,id"), params).mappings()]
    blockers = []
    if not can_execute:
        blockers.append('Tu usuario no tiene permiso para registrar ejecución en esta planta.')
    if operation['project_status'] in {'inactive', 'archived'} or operation['status'] == 'archived':
        blockers.append('El proyecto o la operación está inactivo.')
    if not operation['current_product_definition_revision_id']:
        blockers.append('Falta congelar una definición productiva para esta planta.')
    if not phases:
        blockers.append('La operación no tiene fases configuradas.')
    return {**dict(operation), **choices, 'phases': phases, 'segments': segments,
            'can_execute': can_execute, 'blockers': blockers}
