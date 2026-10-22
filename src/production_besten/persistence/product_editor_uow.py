from datetime import datetime, timezone
from uuid import UUID, uuid4, uuid5
import hashlib
import json
from sqlalchemy import text
from production_besten.domain.errors import EntityNotFound, ProductDefinitionConflict, IdempotencyConflict, InvalidProductDefinition, PrecedenceCycle
from production_besten.domain.product_definition import CreateProductionBatch, DefineBatchRoute, CreateRequiredOperation, CreateRequiredOperationPhase, CreateProductDefinitionRevision, LaborRequirement, PhysicalRequirement
from production_besten.persistence.product_definition_uow import PostgresProductDefinitionUnitOfWork, canonical_json, _has_cycle


class ProductEditorVersionConflict(ProductDefinitionConflict):
    pass


class PostgresProductEditorUnitOfWork(PostgresProductDefinitionUnitOfWork):
    def rows(self, sql, **params):
        return [dict(r) for r in self.conn.execute(text(sql), params).mappings()]

    def project(self, org, plant, project):
        rows = self.rows('SELECT * FROM core.projects WHERE organization_id=:org AND plant_id=:plant AND id=:project', org=org, plant=plant, project=project)
        if not rows:
            raise EntityNotFound()
        return rows[0]

    def editor_options(self, org, plant):
        if not self.conn.scalar(text('SELECT id FROM core.plants WHERE organization_id=:org AND id=:plant'), {'org':org,'plant':plant}):
            raise EntityNotFound()
        result = {}
        for key, table, scoped in [('operations','production.operation_definitions',False),('skills','capacity.skills',False),('centers','capacity.work_centers',True),('resource_types','capacity.physical_resource_types',False),('resource_groups','capacity.physical_resource_groups',True)]:
            result[key] = self.rows(f"SELECT id,code,name FROM {table} WHERE organization_id=:org AND status='active'" + (' AND plant_id=:plant' if scoped else '') + ' ORDER BY name,id', org=org, plant=plant)
        result['routes'] = self.rows("SELECT v.id,t.code||' / '||v.version_no AS code,t.name||' · Rev '||v.version_no AS name FROM production.route_versions v JOIN production.route_templates t ON t.organization_id=v.organization_id AND t.id=v.route_template_id WHERE v.organization_id=:org AND v.status='published' AND t.status='active' ORDER BY t.name,v.version_no",org=org)
        return result

    def editor_detail(self, org, plant, project):
        p = self.project(org,plant,project)
        latest = self.rows("SELECT action_code,metadata FROM audit.audit_entries WHERE organization_id=:org AND entity_id=:project AND action_code LIKE 'PRODUCT_EDITOR_%' AND action_code<>'PRODUCT_EDITOR_VALIDATE' ORDER BY occurred_at DESC,created_at DESC,id DESC LIMIT 1",org=org,project=project)
        lots = self.rows("SELECT id,code,name,description,quantity,unit FROM core.project_lots WHERE organization_id=:org AND project_id=:project AND status<>'archived' ORDER BY sequence_no,code",org=org,project=project)
        ops = self.rows("SELECT id,project_lot_id,code,name,operation_definition_id FROM production.required_operations WHERE organization_id=:org AND project_id=:project AND status<>'archived' ORDER BY code",org=org,project=project)
        phases = self.rows("SELECT ph.* FROM production.required_operation_phases ph JOIN production.required_operations o ON o.organization_id=ph.organization_id AND o.id=ph.required_operation_id WHERE o.organization_id=:org AND o.project_id=:project AND ph.status<>'archived' ORDER BY ph.sequence_no",org=org,project=project)
        labor = self.rows("SELECT r.* FROM production.operation_labor_requirements r JOIN production.required_operation_phases ph ON ph.organization_id=r.organization_id AND ph.id=r.required_operation_phase_id JOIN production.required_operations o ON o.organization_id=ph.organization_id AND o.id=ph.required_operation_id WHERE o.organization_id=:org AND o.project_id=:project AND r.is_mandatory",org=org,project=project)
        physical = self.rows("SELECT r.* FROM production.operation_physical_requirements r JOIN production.required_operation_phases ph ON ph.organization_id=r.organization_id AND ph.id=r.required_operation_phase_id JOIN production.required_operations o ON o.organization_id=ph.organization_id AND o.id=ph.required_operation_id WHERE o.organization_id=:org AND o.project_id=:project AND r.is_mandatory",org=org,project=project)
        edges = self.rows("SELECT e.*,a.code AS predecessor_code FROM production.operation_precedences e JOIN production.required_operations a ON a.organization_id=e.organization_id AND a.id=e.predecessor_operation_id WHERE a.organization_id=:org AND a.project_id=:project AND e.active",org=org,project=project)
        routes = self.rows("SELECT a.project_lot_id,a.route_version_id FROM production.lot_route_assignments a JOIN core.project_lots l ON l.organization_id=a.organization_id AND l.id=a.project_lot_id WHERE l.organization_id=:org AND l.project_id=:project AND a.is_active",org=org,project=project)
        for op in ops:
            op['predecessor_codes'] = [e['predecessor_code'] for e in edges if e['successor_operation_id']==op['id']]
            op['phases'] = []
            for ph in phases:
                if ph['required_operation_id']!=op['id']: continue
                val = {k:ph[k] for k in ('id','code','name','estimate_kind','original_estimate_minutes','split_policy')}
                val['labor_requirements'] = [{k:r[k] for k in ('skill_id','min_people','max_people','work_minutes','productivity_curve','is_mandatory')} for r in labor if r['required_operation_phase_id']==ph['id']]
                val['physical_requirements'] = [{k:r[k] for k in ('physical_resource_type_id','physical_resource_group_id','work_center_id','quantity','capacity_units','usage_mode','is_mandatory')} for r in physical if r['required_operation_phase_id']==ph['id']]
                op['phases'].append(val)
        for lot in lots:
            lot['route_version_id'] = next((r['route_version_id'] for r in routes if r['project_lot_id']==lot['id']),None)
            # Topological ordering follows the saved route, with code as deterministic fallback.
            remaining = [o for o in ops if o['project_lot_id']==lot['id']]
            ordered=[]
            while remaining:
                ready=next((o for o in remaining if not set(o['predecessor_codes']) & {r['code'] for r in remaining}),remaining[0])
                remaining.remove(ready);ordered.append({k:v for k,v in ready.items() if k!='project_lot_id'})
            lot['operations']=ordered
        revisions=[]
        for r in self.rows('SELECT id,revision_no,created_at,canonical_snapshot FROM production.product_definition_revisions WHERE organization_id=:org AND plant_id=:plant ORDER BY revision_no DESC',org=org,plant=plant):
            snapshot=next((v for v in r['canonical_snapshot'].get('projects',[]) if v['code']==p['code']),None)
            if snapshot and any(o.get('phases') for l in snapshot.get('lots',[]) for o in l.get('operations',[])):
                revisions.append({'id':r['id'],'revision_no':r['revision_no'],'created_at':r['created_at'].isoformat(),'lot_count':len(snapshot['lots']),'operation_count':sum(len(l['operations']) for l in snapshot['lots']),'snapshot':snapshot})
        frozen=bool(latest and latest[0]['action_code']=='PRODUCT_EDITOR_FREEZE')
        return {'project_id':project,'row_version':p['row_version'],'draft_id':latest[0]['metadata'].get('draft_id') if latest else None,'status':'frozen' if frozen else ('draft' if lots or latest else 'empty'),'lots':lots,'errors':[] if frozen else self.validate_lots(org,plant,lots),'revisions':revisions,'idempotent_replay':False}

    def validate_lots(self,org,plant,lots):
        errors=[]
        options=self.editor_options(org,plant)
        active={k:{str(r['id']) for r in v} for k,v in options.items()}
        if not lots: errors.append('Agregá al menos un lote productivo.')
        seen_lots=set()
        for l in lots:
            prefix=l['name']+': '
            if l['code'] in seen_lots: errors.append(prefix+'Código de lote repetido.')
            seen_lots.add(l['code'])
            if str(l.get('route_version_id')) not in active['routes']: errors.append(prefix+'Seleccioná una ruta publicada activa.')
            if not l['operations']: errors.append(prefix+'Agregá operaciones a la ruta.')
            codes=[o['code'] for o in l['operations']]
            if len(set(codes))!=len(codes): errors.append(prefix+'Códigos de operación repetidos.')
            edges=[]
            for i,o in enumerate(l['operations']):
                label=prefix+o['name']+': '
                if str(o['operation_definition_id']) not in active['operations']: errors.append(label+'Tipo de operación inactivo o inexistente.')
                for pred in o['predecessor_codes']:
                    edges.append((pred,o['code']))
                    if pred not in codes or pred==o['code']: errors.append(label+'Precedencia fuera del lote o sobre sí misma.')
                    elif codes.index(pred)>=i: errors.append(label+'El orden debe respetar las precedencias.')
                if not o['phases']: errors.append(label+'Agregá al menos una fase con duración.')
                if len({p['code'] for p in o['phases']})!=len(o['phases']): errors.append(label+'Códigos de fase repetidos.')
                for ph in o['phases']:
                    if ph['original_estimate_minutes']<=0: errors.append(label+'La duración debe ser mayor que cero minutos.')
                    for req in ph['labor_requirements']:
                        if str(req['skill_id']) not in active['skills']: errors.append(label+'Habilidad inactiva o inexistente.')
                        if req['min_people']<1 or req['max_people']<req['min_people'] or req['work_minutes']<=0: errors.append(label+'Requisito humano incoherente.')
                    for req in ph['physical_requirements']:
                        for field,option in [('work_center_id','centers'),('physical_resource_type_id','resource_types'),('physical_resource_group_id','resource_groups')]:
                            if req.get(field) and str(req[field]) not in active[option]: errors.append(label+'Centro o recurso inactivo, inexistente o de otra planta.')
                        if req['capacity_units']<=0 or req['quantity']<=0: errors.append(label+'La demanda de capacidad debe ser positiva.')
            if _has_cycle(edges): errors.append(prefix+'Las precedencias contienen un ciclo.')
        return errors

    def editor_execute(self,org,plant,actor,key,project,action,body):
        if action not in {'save','validate','freeze','new-revision'}: raise EntityNotFound()
        self.conn.execute(text('SELECT id FROM core.organizations WHERE id=:org FOR UPDATE'),{'org':org})
        self._lock_plant(org,plant);self._require_actor(org,actor)
        self.conn.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key,0))'),{'key':str(key)})
        digest=hashlib.sha256(json.dumps([str(org),str(plant),str(actor),str(project),action,body],default=str,sort_keys=True).encode()).hexdigest()
        replay=self.rows('SELECT metadata,after_data FROM audit.audit_entries WHERE organization_id=:org AND request_id=:key LIMIT 1',org=org,key=key)
        if replay:
            if replay[0]['metadata'].get('editor_hash')!=digest: raise IdempotencyConflict('La clave corresponde a otra intención o contexto.')
            return replay[0]['after_data']|{'idempotent_replay':True}
        p=self.project(org,plant,project)
        self.conn.execute(text('SELECT id FROM core.projects WHERE organization_id=:org AND id=:project FOR UPDATE'),{'org':org,'project':project})
        if p['row_version']!=body['expected_row_version']:
            raise ProductEditorVersionConflict('La definición productiva cambió desde que la abriste. Actualizá antes de guardar.')
        if p['status']=='archived': raise ProductDefinitionConflict('El proyecto archivado es de sólo lectura.')
        before=self.editor_detail(org,plant,project)
        if before['status']=='frozen' and action in {'save','freeze'}:
            raise ProductDefinitionConflict('La revisión está congelada. Creá una nueva revisión.')
        if action=='new-revision' and before['status']!='frozen': raise ProductDefinitionConflict('Ya existe un borrador editable.')
        if action=='new-revision':
            self.conn.execute(text('SELECT id FROM production.required_operations WHERE organization_id=:org AND project_id=:project ORDER BY id FOR UPDATE'),{'org':org,'project':project})
            if self.conn.scalar(text('SELECT EXISTS(SELECT 1 FROM execution.operation_executions e JOIN production.required_operations o ON o.organization_id=e.organization_id AND o.id=e.required_operation_id WHERE o.organization_id=:org AND o.project_id=:project)'),{'org':org,'project':project}):
                raise ProductDefinitionConflict('La definición tiene ejecución registrada. La revisión de trabajo ejecutado requiere un flujo específico.')
        draft_id=uuid4() if action=='new-revision' or not before['draft_id'] else UUID(str(before['draft_id']))
        if action=='save': self.save_lots(org,plant,actor,key,project,body['lots'])
        elif action=='freeze':
            if before['errors']: raise InvalidProductDefinition(' · '.join(before['errors']))
            self._editor_project=project
            revision=self.create_product_definition_revision(CreateProductDefinitionRevision(org,plant,actor,key,body['reason']))
            if revision.semantic_duplicate:
                raise ProductDefinitionConflict('No hay cambios productivos para congelar una nueva revisión.')
            self.conn.execute(text("UPDATE planning.scenarios SET status='stale',row_version=row_version+1,updated_at=now() WHERE organization_id=:org AND plant_id=:plant AND status IN ('draft','calculating','ready')"),{'org':org,'plant':plant})
            # Preserve CURRENT; expose persistent reconciliation using the existing state revision.
            self.conn.execute(text("UPDATE planning.planning_state_revisions SET change_summary=change_summary||jsonb_build_object('project_id',CAST(:project AS text),'current_affected',EXISTS(SELECT 1 FROM core.plants p JOIN planning.plan_versions v ON v.organization_id=p.organization_id AND v.id=p.current_plan_version_id JOIN planning.operation_plan_results r ON r.organization_id=v.organization_id AND r.schedule_solution_id=v.schedule_solution_id JOIN production.required_operations o ON o.organization_id=r.organization_id AND o.id=r.required_operation_id WHERE p.organization_id=:org AND p.id=:plant AND o.project_id=:project)) WHERE organization_id=:org AND id=(SELECT current_revision_id FROM planning.planning_state_heads WHERE organization_id=:org AND plant_id=:plant)"),{'org':org,'plant':plant,'project':project})
        self.conn.execute(text('UPDATE core.projects SET row_version=row_version+1,updated_at=now() WHERE organization_id=:org AND id=:project'),{'org':org,'project':project})
        metadata={'editor_hash':digest,'draft_id':str(draft_id),'plant_id':str(plant)}
        # Audit lifecycle first so detail reflects the new state; fill replay result in this transaction.
        audit=uuid4()
        self.conn.execute(text("INSERT INTO audit.audit_entries(id,organization_id,actor_user_id,action_code,entity_type,entity_id,request_id,transaction_key,metadata) VALUES (:id,:org,:actor,:action,'project',:project,:key,:key,CAST(:metadata AS jsonb))"),{'id':audit,'org':org,'actor':actor,'action':'PRODUCT_EDITOR_'+action.upper().replace('-','_'),'project':project,'key':key,'metadata':json.dumps(metadata)})
        result=self.editor_detail(org,plant,project)
        if action=='validate' and before['status']=='frozen': result['status']='frozen'
        self.conn.execute(text('UPDATE audit.audit_entries SET after_data=CAST(:result AS jsonb) WHERE id=:id AND organization_id=:org'),{'id':audit,'org':org,'result':json.dumps(result,default=str)})
        if self._failpoint=='after_editor': raise RuntimeError('editor rollback probe')
        return result

    def _build_snapshot(self,org,plant):
        snapshot=super()._build_snapshot(org,plant)
        current=self.conn.scalar(text('SELECT d.canonical_snapshot FROM core.plants p JOIN production.product_definition_revisions d ON d.organization_id=p.organization_id AND d.id=p.current_product_definition_revision_id WHERE p.organization_id=:org AND p.id=:plant'),{'org':org,'plant':plant}) or {}
        code=self.project(org,plant,self._editor_project)['code']
        # Other projects retain their frozen demand while this project's normalized draft is frozen.
        previous={p['code']:p for p in current.get('projects',[])}
        merged={**previous,code:next(p for p in snapshot['projects'] if p['code']==code)}
        snapshot['projects']=[merged[c] for c in sorted(merged)]
        snapshot['editor_frozen_projects']=sorted(set(current.get('editor_frozen_projects',[]))|{code})
        return snapshot

    def save_lots(self,org,plant,actor,key,project,lots):
        errors=self.validate_lots(org,plant,lots)
        # Incomplete drafts are allowed; reject identity, graph and active-master violations on save.
        blockers=[e for e in errors if any(w in e for w in ('repetid','inactiv','inexistente','otra planta','fuera del lote','sí misma','precedencias','orden debe','incoherente'))]
        if blockers: raise ProductDefinitionConflict(' · '.join(blockers))
        def command_id(label): return uuid5(key,label)
        old_lots={r['id']:r for r in self.rows('SELECT * FROM core.project_lots WHERE organization_id=:org AND project_id=:project',org=org,project=project)}
        old_ops={r['id']:r for r in self.rows('SELECT * FROM production.required_operations WHERE organization_id=:org AND project_id=:project ORDER BY id FOR UPDATE',org=org,project=project)}
        old_phases={r['id']:r for r in self.rows('SELECT ph.* FROM production.required_operation_phases ph JOIN production.required_operations o ON o.organization_id=ph.organization_id AND o.id=ph.required_operation_id WHERE o.organization_id=:org AND o.project_id=:project',org=org,project=project)}
        # Execution keeps its definition; the UI must not revise work with recorded reality.
        if self.conn.scalar(text('SELECT EXISTS(SELECT 1 FROM execution.operation_executions e JOIN production.required_operations o ON o.organization_id=e.organization_id AND o.id=e.required_operation_id WHERE o.organization_id=:org AND o.project_id=:project)'),{'org':org,'project':project}):
            raise ProductDefinitionConflict('La definición tiene ejecución registrada. La revisión de trabajo ejecutado requiere un flujo específico.')
        for i,ident in enumerate(old_lots): self.conn.execute(text('UPDATE core.project_lots SET sequence_no=:seq WHERE organization_id=:org AND id=:id'),{'seq':30000+i,'org':org,'id':ident})
        for i,ident in enumerate(old_phases): self.conn.execute(text('UPDATE production.required_operation_phases SET sequence_no=:seq WHERE organization_id=:org AND id=:id'),{'seq':30000+i,'org':org,'id':ident})
        kept_lots=[];kept_ops=[];kept_phases=[]
        for li,l in enumerate(lots,1):
            lid=l.get('id')
            if lid:
                if lid not in old_lots or old_lots[lid]['code']!=l['code']: raise EntityNotFound()
                self.conn.execute(text("UPDATE core.project_lots SET name=:name,description=:description,quantity=:quantity,unit=:unit,sequence_no=:seq,status='draft',row_version=row_version+1,updated_at=now() WHERE organization_id=:org AND id=:id"),l|{'org':org,'id':lid,'seq':li})
            else:
                lid=self.create_production_batch(CreateProductionBatch(org,project,l['code'],l['name'],actor,command_id('lot'+str(li)),description=l['description'],sequence_no=li,quantity=l['quantity'],unit=l['unit'])).entity_id
            kept_lots.append(lid)
            route=l.get('route_version_id')
            manual = route is None or bool(self.conn.scalar(text("SELECT EXISTS(SELECT 1 FROM production.route_versions v JOIN production.route_templates t ON t.organization_id=v.organization_id AND t.id=v.route_template_id WHERE v.organization_id=:org AND v.id=:route AND t.code=:code)"),{'org':org,'route':route,'code':'LOT_ROUTE_'+lid.hex}))
            if manual and l['operations'] and all(o['phases'] and all(p['original_estimate_minutes']>0 for p in o['phases']) for o in l['operations']):
                route=self.manual_route(org,actor,lid,l)
            current=self.conn.scalar(text('SELECT route_version_id FROM production.lot_route_assignments WHERE organization_id=:org AND project_lot_id=:lot AND is_active'),{'org':org,'lot':lid})
            if route and route!=current: self.define_batch_route(DefineBatchRoute(org,lid,route,datetime.now(timezone.utc),actor,command_id('route'+str(li))))
            if not route and current:
                self.conn.execute(text("UPDATE production.lot_route_assignments SET is_active=false,valid_during=tstzrange(lower(valid_during),now(),'[)') WHERE organization_id=:org AND project_lot_id=:lot AND is_active"),{'org':org,'lot':lid})
            op_ids={}
            for oi,o in enumerate(l['operations']):
                oid=o.get('id')
                if oid:
                    if oid not in old_ops or old_ops[oid]['project_lot_id']!=lid or old_ops[oid]['code']!=o['code']: raise EntityNotFound()
                    self.conn.execute(text("UPDATE production.required_operations SET name=:name,operation_definition_id=:operation_definition_id,status='draft',row_version=row_version+1,updated_at=now() WHERE organization_id=:org AND id=:id"),o|{'org':org,'id':oid})
                else: oid=self.create_required_operation(CreateRequiredOperation(org,project,o['operation_definition_id'],o['code'],o['name'],actor,command_id(f'op{li}:{oi}'),project_lot_id=lid)).entity_id
                kept_ops.append(oid);op_ids[o['code']]=oid
                for pi,ph in enumerate(o['phases'],1):
                    pid=ph.get('id')
                    if pid:
                        if pid not in old_phases or old_phases[pid]['required_operation_id']!=oid or old_phases[pid]['code']!=ph['code']: raise EntityNotFound()
                        self.conn.execute(text("UPDATE production.required_operation_phases SET name=:name,sequence_no=:seq,estimate_kind=:estimate_kind,original_estimate_minutes=:original_estimate_minutes,split_policy=:split_policy,status='draft',row_version=row_version+1,updated_at=now() WHERE organization_id=:org AND id=:id"),ph|{'org':org,'id':pid,'seq':pi})
                    else: pid=self.create_required_operation_phase(CreateRequiredOperationPhase(org,oid,pi,ph['code'],ph['name'],ph['estimate_kind'],ph['original_estimate_minutes'],ph['split_policy'],actor,command_id(f'phase{li}:{oi}:{pi}'))).entity_id
                    kept_phases.append(pid)
                    self.conn.execute(text('DELETE FROM production.operation_labor_requirements WHERE organization_id=:org AND required_operation_phase_id=:phase'),{'org':org,'phase':pid})
                    for req in ph['labor_requirements']:
                        LaborRequirement(**req).validate()
                        self.conn.execute(text('INSERT INTO production.operation_labor_requirements(organization_id,required_operation_phase_id,skill_id,min_people,max_people,work_minutes,productivity_curve,is_mandatory) VALUES (:org,:phase,:skill_id,:min_people,:max_people,:work_minutes,CAST(:curve AS jsonb),:is_mandatory)'),req|{'org':org,'phase':pid,'curve':json.dumps(req['productivity_curve'])})
                    existing=self.rows('SELECT id FROM production.operation_physical_requirements WHERE organization_id=:org AND required_operation_phase_id=:phase ORDER BY created_at,id',org=org,phase=pid)
                    self.conn.execute(text('UPDATE production.operation_physical_requirements SET is_mandatory=false WHERE organization_id=:org AND required_operation_phase_id=:phase'),{'org':org,'phase':pid})
                    for ri,req in enumerate(ph['physical_requirements']):
                        PhysicalRequirement(**req).validate()
                        rid=existing[ri]['id'] if ri<len(existing) else uuid4()
                        self.conn.execute(text('INSERT INTO production.operation_physical_requirements(id,organization_id,required_operation_phase_id,physical_resource_type_id,physical_resource_group_id,work_center_id,quantity,capacity_units,usage_mode,is_mandatory) VALUES (:id,:org,:phase,:physical_resource_type_id,:physical_resource_group_id,:work_center_id,:quantity,:capacity_units,:usage_mode,:is_mandatory) ON CONFLICT(id) DO UPDATE SET physical_resource_type_id=EXCLUDED.physical_resource_type_id,physical_resource_group_id=EXCLUDED.physical_resource_group_id,work_center_id=EXCLUDED.work_center_id,quantity=EXCLUDED.quantity,capacity_units=EXCLUDED.capacity_units,usage_mode=EXCLUDED.usage_mode,is_mandatory=EXCLUDED.is_mandatory'),req|{'id':rid,'org':org,'phase':pid})
            self.conn.execute(text('UPDATE production.operation_precedences SET active=false WHERE organization_id=:org AND successor_operation_id=ANY(:ids)'),{'org':org,'ids':list(op_ids.values())})
            for o in l['operations']:
                for pred in o['predecessor_codes']:
                    self.conn.execute(text("INSERT INTO production.operation_precedences(organization_id,predecessor_operation_id,successor_operation_id,source) VALUES (:org,:pred,:succ,'manual')"),{'org':org,'pred':op_ids[pred],'succ':op_ids[o['code']]})
        for table,old,kept in [('core.project_lots',old_lots,kept_lots),('production.required_operations',old_ops,kept_ops),('production.required_operation_phases',old_phases,kept_phases)]:
            removed=list(set(old)-set(kept))
            if removed:self.conn.execute(text(f"UPDATE {table} SET status='archived',row_version=row_version+1,updated_at=now() WHERE organization_id=:org AND id=ANY(:ids)"),{'org':org,'ids':removed})

    def manual_route(self,org,actor,lot_id,lot):
        """A lot-specific versioned route, without a reusable product-template catalog."""
        code='LOT_ROUTE_'+lot_id.hex
        template=self.conn.scalar(text('SELECT id FROM production.route_templates WHERE organization_id=:org AND code=:code'),{'org':org,'code':code})
        if template is None:
            template=uuid4()
            self.conn.execute(text("INSERT INTO production.route_templates(id,organization_id,code,name,status) VALUES (:id,:org,:code,:name,'active')"),{'id':template,'org':org,'code':code,'name':'Ruta de '+lot['name']})
        content=[{k:o[k] for k in ('code','name','operation_definition_id','predecessor_codes')}|{'phases':o['phases']} for o in lot['operations']]
        digest=hashlib.sha256(json.dumps(content,default=str,sort_keys=True).encode()).hexdigest()
        existing=self.rows('SELECT id,version_no,notes FROM production.route_versions WHERE organization_id=:org AND route_template_id=:template ORDER BY version_no DESC LIMIT 1',org=org,template=template)
        if existing and existing[0]['notes']==digest:return existing[0]['id']
        version=uuid4();number=existing[0]['version_no']+1 if existing else 1
        self.conn.execute(text("INSERT INTO production.route_versions(id,organization_id,route_template_id,version_no,status,notes) VALUES (:id,:org,:template,:number,'draft',:digest)"),{'id':version,'org':org,'template':template,'number':number,'digest':digest})
        steps={}
        for i,op in enumerate(lot['operations'],1):
            step=uuid4();steps[op['code']]=step
            self.conn.execute(text('INSERT INTO production.route_steps(id,organization_id,route_version_id,operation_definition_id,code,name,sequence_hint) VALUES (:id,:org,:version,:definition,:code,:name,:seq)'),{'id':step,'org':org,'version':version,'definition':op['operation_definition_id'],'code':op['code'],'name':op['name'],'seq':i})
            for j,ph in enumerate(op['phases'],1):
                self.conn.execute(text('INSERT INTO production.route_step_phase_templates(organization_id,route_step_id,sequence_no,code,name,estimate_kind,original_estimate_minutes,split_policy) VALUES (:org,:step,:seq,:code,:name,:kind,:minutes,:split)'),{'org':org,'step':step,'seq':j,'code':ph['code'],'name':ph['name'],'kind':ph['estimate_kind'],'minutes':ph['original_estimate_minutes'],'split':ph['split_policy']})
        for op in lot['operations']:
            for pred in op['predecessor_codes']:
                self.conn.execute(text('INSERT INTO production.route_step_precedences(organization_id,route_version_id,predecessor_step_id,successor_step_id) VALUES (:org,:version,:pred,:succ)'),{'org':org,'version':version,'pred':steps[pred],'succ':steps[op['code']]})
        self.conn.execute(text("UPDATE production.route_versions SET status='published',published_at=now(),published_by=:actor WHERE organization_id=:org AND id=:id"),{'org':org,'id':version,'actor':actor})
        return version
