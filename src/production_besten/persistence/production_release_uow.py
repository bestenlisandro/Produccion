from datetime import datetime,timezone
from decimal import Decimal
from uuid import uuid4
import hashlib,json
from sqlalchemy import text
from production_besten.domain.errors import EntityNotFound,IdempotencyConflict
from production_besten.application.production_release_services import ProductionReleaseConflict,ProductionReleaseVersionConflict
from production_besten.persistence.product_definition_uow import PostgresProductDefinitionUnitOfWork,canonical_json

RELEASED='PROJECT_PRODUCTION_RELEASED'
WITHDRAWN='PROJECT_PRODUCTION_WITHDRAWN'


def definition_digest(project):
    # Administrative priority/dates do not revoke an industrial authorization.
    value=None if project is None else {k:project.get(k) for k in ('lots','unassigned_operations')}
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def release_events(conn,org,plant):
    return [dict(r) for r in conn.execute(text('''SELECT e.*,r.revision_no FROM planning.effective_events e
        LEFT JOIN planning.planning_state_revisions r ON r.organization_id=e.organization_id AND r.id=e.planning_state_revision_id
        WHERE e.organization_id=:org AND e.plant_id=:plant AND e.entity_type='project'
        AND e.event_type_code IN ('PROJECT_PRODUCTION_RELEASED','PROJECT_PRODUCTION_WITHDRAWN')
        ORDER BY r.revision_no DESC NULLS LAST,e.effective_at DESC,e.created_at DESC,e.id DESC'''),{'org':org,'plant':plant}).mappings()]


class PostgresProductionReleaseUnitOfWork(PostgresProductDefinitionUnitOfWork):
    def rows(self,sql,**params):return [dict(r) for r in self.conn.execute(text(sql),params).mappings()]

    def readiness(self,org,plant):
        plants=self.rows('SELECT p.*,clock_timestamp() AS evaluated_at,d.canonical_snapshot,d.revision_no,h.current_revision_id FROM core.plants p LEFT JOIN production.product_definition_revisions d ON d.organization_id=p.organization_id AND d.id=p.current_product_definition_revision_id LEFT JOIN planning.planning_state_heads h ON h.organization_id=p.organization_id AND h.plant_id=p.id WHERE p.organization_id=:org AND p.id=:plant',org=org,plant=plant)
        if not plants:raise EntityNotFound()
        pl=plants[0];snapshot=pl['canonical_snapshot'] or {};now=pl['evaluated_at']
        projects=self.rows('SELECT * FROM core.projects WHERE organization_id=:org AND plant_id=:plant ORDER BY code',org=org,plant=plant)
        editor=self.rows("SELECT DISTINCT ON(entity_id) entity_id,action_code FROM audit.audit_entries WHERE organization_id=:org AND entity_type='project' AND action_code LIKE 'PRODUCT_EDITOR_%' AND action_code<>'PRODUCT_EDITOR_VALIDATE' ORDER BY entity_id,occurred_at DESC,created_at DESC,id DESC",org=org)
        draft={r['entity_id']:r['action_code']!='PRODUCT_EDITOR_FREEZE' for r in editor}
        events=release_events(self.conn,org,plant);latest={}
        for e in events:latest.setdefault(e['entity_id'],e)
        facts=self.rows('''SELECT m.*,d.code FROM core.project_milestones m JOIN core.milestone_definitions d ON d.organization_id=m.organization_id AND d.id=m.milestone_definition_id
            JOIN core.projects p ON p.organization_id=m.organization_id AND p.id=m.project_id WHERE m.organization_id=:org AND p.plant_id=:plant
            AND NOT EXISTS(SELECT 1 FROM core.project_milestones n WHERE n.organization_id=m.organization_id AND n.supersedes_id=m.id)''',org=org,plant=plant)
        fact_by={(f['project_id'],f['code']):f for f in facts}
        catalogs={}
        for key,table,scoped in [('operations','production.operation_definitions',False),('skills','capacity.skills',False),('centers','capacity.work_centers',True),('types','capacity.physical_resource_types',False),('groups','capacity.physical_resource_groups',True)]:
            catalogs[key]={r['code']:r for r in self.rows(f'SELECT * FROM {table} WHERE organization_id=:org'+(' AND plant_id=:plant' if scoped else ''),org=org,plant=plant)}
        materials=self.rows('''SELECT m.*,l.code AS lot_code,l.project_id FROM production.material_requirements m JOIN core.project_lots l ON l.organization_id=m.organization_id AND l.id=m.project_lot_id JOIN core.projects p ON p.organization_id=l.organization_id AND p.id=l.project_id WHERE m.organization_id=:org AND p.plant_id=:plant''',org=org,plant=plant)
        allocations=self.rows('''SELECT a.material_requirement_id,a.quantity*a.movement_sign AS quantity,d.delivered_at
            FROM production.material_allocations a JOIN production.supplier_delivery_lines dl ON dl.organization_id=a.organization_id AND dl.id=a.supplier_delivery_line_id
            JOIN production.supplier_deliveries d ON d.organization_id=dl.organization_id AND d.id=dl.supplier_delivery_id
            WHERE a.organization_id=:org AND NOT EXISTS(SELECT 1 FROM production.material_allocations n WHERE n.organization_id=a.organization_id AND n.supersedes_id=a.id)
            AND NOT EXISTS(SELECT 1 FROM production.supplier_deliveries n WHERE n.organization_id=d.organization_id AND n.supersedes_id=d.id)''',org=org)
        quantities={}
        for a in allocations:
            if a['delivered_at']<=now:quantities[a['material_requirement_id']]=quantities.get(a['material_requirement_id'],Decimal(0))+a['quantity']
        material_by={(r['project_id'],r['lot_code'],r['code']):r for r in materials}
        drawings=self.rows('''SELECT d.*,l.project_id,l.code AS lot_code FROM production.drawing_packages d JOIN core.project_lots l ON l.organization_id=d.organization_id AND l.id=d.project_lot_id JOIN core.projects p ON p.organization_id=l.organization_id AND p.id=l.project_id WHERE d.organization_id=:org AND p.plant_id=:plant''',org=org,plant=plant)
        drawing_by={(d['project_id'],d['lot_code'],d['code']):d for d in drawings}
        releases=self.rows("SELECT r.* FROM production.drawing_releases r WHERE organization_id=:org AND NOT EXISTS(SELECT 1 FROM production.drawing_releases n WHERE n.organization_id=r.organization_id AND n.supersedes_id=r.id)",org=org)
        released_drawings={r['drawing_package_id'] for r in releases if r['status']=='released' and r['released_at'] and r['released_at']<=now}
        lots=self.rows('SELECT l.* FROM core.project_lots l JOIN core.projects p ON p.organization_id=l.organization_id AND p.id=l.project_id WHERE l.organization_id=:org AND p.plant_id=:plant',org=org,plant=plant)
        lot_by={(l['project_id'],l['code']):l for l in lots}
        result={}
        for p in projects:
            definition=next((d for d in snapshot.get('projects',[]) if d['code']==p['code']),None)
            items=[]
            def add(code,label,ok,detail,applicable=True):items.append({'code':code,'label':label,'satisfied':bool(ok),'detail':detail,'applicable':applicable})
            add('PROJECT_ACTIVE','Proyecto activo',p['status']=='active','El proyecto debe estar activo para liberar; prioridad y compromiso siguen separados.')
            operations=[]
            if definition:
                operations=definition.get('unassigned_operations',[])+[o for l in definition.get('lots',[]) for o in l.get('operations',[])]
            valid=bool(operations and all(o.get('phases') and all(ph['original_estimate_minutes']>0 for ph in o['phases']) for o in operations))
            add('FROZEN_DEFINITION','Definición productiva congelada',valid,'REV '+str(pl['revision_no']) if valid else 'Falta una definición productiva congelada con operaciones y fases válidas.')
            add('NO_PENDING_DRAFT','Definición sin borrador pendiente',not draft.get(p['id'],False),'Un borrador debe congelarse antes de una nueva liberación.')
            inactive=[];gates=[]
            for o in operations:
                if catalogs['operations'].get(o['operation_definition_code'],{}).get('status')!='active':inactive.append(o['operation_definition_code'])
                gates+=o.get('gates',[])
                for ph in o.get('phases',[]):
                    gates+=ph.get('gates',[])
                    for r in ph['labor_requirements']:
                        if r['is_mandatory'] and catalogs['skills'].get(r['code'],{}).get('status')!='active':inactive.append(r['code'])
                    for r in ph['physical_requirements']:
                        if not r['is_mandatory']:continue
                        for field,key in [('work_center_code','centers'),('resource_type_code','types'),('resource_group_code','groups')]:
                            if r.get(field) and catalogs[key].get(r[field],{}).get('status')!='active':inactive.append(r[field])
            add('ACTIVE_MASTERS','Maestros productivos activos',not inactive,'Inactivos o fuera de planta: '+', '.join(sorted(set(inactive))) if inactive else 'Centros, tipos de operación, skills y selectores de recursos activos.')
            required_milestones={g['milestone_code'] for g in gates if g.get('milestone_code')}
            for code,label in [('MEASUREMENT','Medición realizada'),('REPLANTEO','Replanteo realizado')]+[(c,c) for c in sorted(required_milestones-{'MEASUREMENT','REPLANTEO'})]:
                applicable=code in required_milestones;fact=fact_by.get((p['id'],code));ok=bool(fact and fact['occurred_at']<=now)
                add('MILESTONE:'+code,label,ok or not applicable,fact['occurred_at'].isoformat() if fact else ('Pendiente: requerido por el proceso.' if applicable else 'No exigido por los gates de esta definición.'),applicable)
            required_materials={(l['code'],m['code']):m for l in (definition or {}).get('lots',[]) for m in l.get('materials',[]) if m['is_mandatory']}
            required_drawings={(l['code'],d['code']):d for l in (definition or {}).get('lots',[]) for d in l.get('drawing_packages',[]) if d['required']}
            for g in gates:
                if g.get('material_code'):required_materials.setdefault((g['material_lot_code'],g['material_code']),None)
                if g.get('drawing_code'):required_drawings.setdefault((g['drawing_lot_code'],g['drawing_code']),None)
            for (lot_code,code),frozen in required_materials.items():
                material=material_by.get((p['id'],lot_code,code));needed=Decimal(str(frozen['required_quantity'])) if frozen else (material['required_quantity'] if material else Decimal(1))
                net=quantities.get(material['id'],Decimal(0)) if material else Decimal(0)
                add('MATERIAL:'+lot_code+':'+code,'Material '+code,material is not None and net>=needed,f'Asignado {net} / requerido {needed}; recepción propia, sin stock ni compras.')
            for lot_code,code in required_drawings:
                d=drawing_by.get((p['id'],lot_code,code));add('DRAWING:'+lot_code+':'+code,'Documentación '+code,d is not None and d['id'] in released_drawings,'Requiere una liberación de plano vigente y realizada.')
            for i,g in enumerate(gates):
                if g.get('hardware_lot_code'):
                    l=lot_by.get((p['id'],g['hardware_lot_code']));ok=l and l['hardware_status'] in {'ready','not_required'} and (not l['hardware_available_at'] or l['hardware_available_at']<=now)
                    add('HARDWARE:'+str(i),'Herrajes '+g['hardware_lot_code'],ok,'Disponibilidad del lote según su estado real.')
                elif g.get('available_at'):add('DATE:'+str(i),g['gate_type'],datetime.fromisoformat(g['available_at'].replace('Z','+00:00'))<=now,'Disponible desde '+g['available_at'])
            ready=all(i['satisfied'] for i in items)
            base_ready=all(i['satisfied'] for i in items if i['code']!='NO_PENDING_DRAFT')
            event=latest.get(p['id']);digest=definition_digest(definition)
            released=bool(event and event['event_type_code']==RELEASED and event['payload'].get('project_definition_sha256')==digest)
            eligible=released and base_ready
            state='released' if eligible else ('ready' if ready else ('blocked' if definition else 'not_ready'))
            token_data={'project_version':p['row_version'],'definition_id':str(pl['current_product_definition_revision_id']),'head':str(pl['current_revision_id']),'event':str(event['id']) if event else None,'items':items,'definition_digest':digest}
            token=hashlib.sha256(json.dumps(token_data,sort_keys=True,default=str).encode()).hexdigest()
            history=[{'event':e['event_type_code'],'at':e['occurred_at'].isoformat(),'actor':str(e['created_by']),'definition_revision_no':e['payload'].get('definition_revision_no')} for e in events if e['entity_id']==p['id']]
            result[p['id']]={'project_id':p['id'],'row_version':p['row_version'],'evaluation_token':token,'evaluated_at':now.isoformat(),'state':state,'ready':ready,'released':released,'eligible':eligible,'definition_revision_id':pl['current_product_definition_revision_id'] if valid else None,'definition_revision_no':pl['revision_no'] if valid else None,'released_at':event['occurred_at'].isoformat() if released else None,'items':items,'history':history,'idempotent_replay':False}
        return result

    def release_project(self,org,plant,actor,key,project,action,body):
        self.conn.execute(text('SELECT id FROM core.organizations WHERE id=:org FOR UPDATE'),{'org':org})
        self._lock_plant(org,plant);self._require_actor(org,actor)
        self.conn.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key,0))'),{'key':str(key)})
        intent=hashlib.sha256(json.dumps([str(org),str(plant),str(actor),str(project),action,body],default=str,sort_keys=True).encode()).hexdigest()
        replay=self.rows('SELECT metadata,after_data FROM audit.audit_entries WHERE organization_id=:org AND request_id=:key LIMIT 1',org=org,key=key)
        if replay:
            if replay[0]['metadata'].get('release_hash')!=intent:raise IdempotencyConflict('La clave corresponde a otra intención o contexto.')
            return replay[0]['after_data']|{'idempotent_replay':True}
        p=self.conn.execute(text('SELECT * FROM core.projects WHERE organization_id=:org AND plant_id=:plant AND id=:id FOR UPDATE'),{'org':org,'plant':plant,'id':project}).mappings().one_or_none()
        if p is None:raise EntityNotFound()
        before=self.readiness(org,plant)[project]
        if p['row_version']!=body['expected_row_version'] or before['evaluation_token']!=body['evaluation_token']:
            raise ProductionReleaseVersionConflict('El proyecto cambió desde que verificaste su preparación. Actualizá y volvé a revisar antes de liberar.')
        if action=='simulate':
            if not before['eligible']:raise ProductionReleaseConflict('El proyecto no tiene una liberación vigente y preparada para simular.')
            from dataclasses import asdict
            from production_besten.persistence.scheduling_uow import PostgresSchedulingUnitOfWork
            from production_besten.domain.scheduling.models import GenerateSchedule
            scheduler=PostgresSchedulingUnitOfWork(self._engine)
            scheduler._connection=self.conn
            state=self.conn.scalar(text('SELECT current_revision_id FROM planning.planning_state_heads WHERE organization_id=:org AND plant_id=:plant'),{'org':org,'plant':plant})
            command=GenerateSchedule(org,plant,actor,'RELEASE-'+key.hex,body['reason'],body['horizon_start'],body['horizon_end'],before['definition_revision_id'],state,(project,))
            result=asdict(scheduler.generate_schedule(command))|{'idempotent_replay':False}
            self.conn.execute(text("INSERT INTO audit.audit_entries(organization_id,actor_user_id,action_code,entity_type,entity_id,request_id,transaction_key,after_data,metadata) VALUES (:org,:actor,'PROJECT_PRODUCTION_SIMULATED','project',:project,:key,:key,CAST(:after AS jsonb),CAST(:metadata AS jsonb))"),{'org':org,'actor':actor,'project':project,'key':key,'after':json.dumps(result,default=str),'metadata':json.dumps({'release_hash':intent})})
            if self._failpoint=='after_release':raise RuntimeError('simulation rollback probe')
            return result
        if action=='release':
            if not before['ready']:raise ProductionReleaseConflict('Falta preparación: '+' · '.join(i['label']+': '+i['detail'] for i in before['items'] if not i['satisfied']))
            if before['released']:raise ProductionReleaseConflict('El proyecto ya está liberado para esta definición.')
        else:
            if not before['released']:raise ProductionReleaseConflict('El proyecto no tiene una liberación vigente.')
            self.conn.execute(text('SELECT id FROM production.required_operations WHERE organization_id=:org AND project_id=:project ORDER BY id FOR UPDATE'),{'org':org,'project':project})
            if self.conn.scalar(text('SELECT EXISTS(SELECT 1 FROM execution.operation_executions e JOIN production.required_operations o ON o.organization_id=e.organization_id AND o.id=e.required_operation_id WHERE o.organization_id=:org AND o.project_id=:project)'),{'org':org,'project':project}):raise ProductionReleaseConflict('Existe ejecución iniciada; no se puede retirar de planificación desde esta acción.')
        event_type=RELEASED if action=='release' else WITHDRAWN
        definition=self.conn.scalar(text('SELECT canonical_snapshot FROM production.product_definition_revisions WHERE organization_id=:org AND id=:id'),{'org':org,'id':before['definition_revision_id']}) or {}
        frozen=next((d for d in definition.get('projects',[]) if d['code']==p['code']),None)
        prior=next((e for e in release_events(self.conn,org,plant) if e['entity_id']==project),None)
        payload={'payload_schema_version':1,'product_definition_revision_id':str(before['definition_revision_id']),'definition_revision_no':before['definition_revision_no'],'project_definition_sha256':definition_digest(frozen),'checklist':before['items'],'evaluation_token':before['evaluation_token']}
        state_id,_=self._advance_state(org,plant,actor,body['reason'],event_type,'project',project,payload,'production_release',str(key))
        if prior:self.conn.execute(text("UPDATE planning.effective_events SET supersedes_id=:prior WHERE organization_id=:org AND source_system='production_release' AND external_reference=:reference"),{'prior':prior['id'],'org':org,'reference':str(key)})
        affected=self.conn.scalar(text('''SELECT EXISTS(SELECT 1 FROM core.plants p JOIN planning.plan_versions v ON v.organization_id=p.organization_id AND v.id=p.current_plan_version_id JOIN planning.operation_plan_results r ON r.organization_id=v.organization_id AND r.schedule_solution_id=v.schedule_solution_id JOIN production.required_operations o ON o.organization_id=r.organization_id AND o.id=r.required_operation_id WHERE p.organization_id=:org AND p.id=:plant AND o.project_id=:project)'''),{'org':org,'plant':plant,'project':project})
        self.conn.execute(text('UPDATE planning.planning_state_revisions SET change_summary=change_summary||CAST(:summary AS jsonb) WHERE organization_id=:org AND id=:id'),{'org':org,'id':state_id,'summary':json.dumps({'project_id':str(project),'current_affected':bool(affected),'production_release':action})})
        self.conn.execute(text("UPDATE planning.scenarios SET status='stale',updated_at=now(),row_version=row_version+1 WHERE organization_id=:org AND plant_id=:plant AND status IN ('draft','calculating','ready')"),{'org':org,'plant':plant})
        self.conn.execute(text('UPDATE core.projects SET row_version=row_version+1,updated_at=now() WHERE organization_id=:org AND id=:id'),{'org':org,'id':project})
        result=self.readiness(org,plant)[project]
        self.conn.execute(text("INSERT INTO audit.audit_entries(organization_id,actor_user_id,action_code,entity_type,entity_id,request_id,transaction_key,before_data,after_data,metadata) VALUES (:org,:actor,:action,'project',:project,:key,:key,CAST(:before AS jsonb),CAST(:after AS jsonb),CAST(:metadata AS jsonb))"),{'org':org,'actor':actor,'action':event_type,'project':project,'key':key,'before':json.dumps(before,default=str),'after':json.dumps(result,default=str),'metadata':json.dumps({'release_hash':intent,'plant_id':str(plant)})})
        if self._failpoint=='after_release':raise RuntimeError('release rollback probe')
        return result


def authorized_projects(conn,org,plant,snapshot,*,check_readiness=False):
    events=release_events(conn,org,plant);latest={}
    for e in events:latest.setdefault(e['entity_id'],e)
    definitions={p['code']:p for p in snapshot.get('projects',[])}
    projects=conn.execute(text('SELECT id,code FROM core.projects WHERE organization_id=:org AND plant_id=:plant'),{'org':org,'plant':plant}).mappings()
    allowed=[p['id'] for p in projects if (e:=latest.get(p['id'])) and e['event_type_code']==RELEASED and e['payload'].get('project_definition_sha256')==definition_digest(definitions.get(p['code']))]
    if check_readiness and definitions:
        adapter=PostgresProductionReleaseUnitOfWork(None)
        adapter._connection=conn
        readiness=adapter.readiness(org,plant)
        allowed=[pid for pid in allowed if readiness[pid]['eligible']]
    return allowed
