from datetime import datetime, timezone
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo
import hashlib
import json

from sqlalchemy import text
from production_besten.domain.errors import EntityNotFound, IdempotencyConflict, ProductDefinitionConflict, InvalidProductDefinition
from production_besten.domain.product_definition import CreateProject
from production_besten.domain.project_intake import ProjectIntakeVersionConflict
from production_besten.persistence.product_definition_uow import PostgresProductDefinitionUnitOfWork


class PostgresProjectIntakeUnitOfWork(PostgresProductDefinitionUnitOfWork):
    def intake_options(self, org, plant):
        p = self.conn.execute(text("SELECT id,code,name,timezone FROM core.plants WHERE organization_id=:org AND id=:plant"), {"org":org,"plant":plant}).mappings().one_or_none()
        if p is None:
            raise EntityNotFound()
        customers = self.conn.execute(text("SELECT id,code,display_name AS name FROM core.customers WHERE organization_id=:org AND status='active' ORDER BY display_name,id"), {"org":org}).mappings().all()
        priorities = self.conn.execute(text("SELECT id,code,name FROM core.project_priorities WHERE organization_id=:org AND status='active' AND code IN ('URGENT','HIGH','NORMAL') ORDER BY rank,id"), {"org":org}).mappings().all()
        return {"customers":[dict(c) for c in customers], "priorities":[dict(p) for p in priorities],
                "plant":{k:p[k] for k in ("id","code","name")},"timezone":p["timezone"],
                "measurement_supported":True,"replanteo_supported":True}

    def list_projects(self, org, plant, *, search="", status=None, priority=None, customer_id=None,
                      committed_from=None, committed_to=None):
        options = self.intake_options(org,plant)
        rows = self.conn.execute(text("""
            SELECT p.*,c.display_name AS customer_name,c.email AS customer_email,c.phone AS customer_phone,
                   pp.code AS priority_code,pp.rank AS priority_rank,
                   (SELECT count(*) FROM core.project_lots l WHERE l.organization_id=p.organization_id AND l.project_id=p.id) AS lot_count,
                   ARRAY(SELECT ro.id FROM production.required_operations ro WHERE ro.organization_id=p.organization_id AND ro.project_id=p.id ORDER BY ro.code,ro.id) AS operation_ids,
                   ARRAY(SELECT ro.id FROM production.required_operations ro JOIN planning.operation_plan_results op ON op.organization_id=ro.organization_id AND op.required_operation_id=ro.id
                     WHERE ro.organization_id=p.organization_id AND ro.project_id=p.id AND op.schedule_solution_id=pv.schedule_solution_id ORDER BY ro.code,ro.id) AS planned_operation_ids,
                   d.revision_no AS plant_revision_no,d.canonical_snapshot,
                   (SELECT CASE WHEN bool_and(op.result_status='planned') THEN max(op.planned_end_at) END
                      FROM planning.operation_plan_results op JOIN production.required_operations ro
                        ON ro.organization_id=op.organization_id AND ro.id=op.required_operation_id
                     WHERE op.organization_id=p.organization_id AND op.schedule_solution_id=pv.schedule_solution_id AND ro.project_id=p.id) AS estimated_at,
                   (SELECT cd.communicated_date FROM portal.communicated_dates cd
                     WHERE cd.organization_id=p.organization_id AND cd.project_id=p.id
                       AND NOT EXISTS(SELECT 1 FROM portal.communicated_dates successor WHERE successor.organization_id=cd.organization_id AND successor.supersedes_id=cd.id)
                     ORDER BY cd.communicated_at DESC,cd.id DESC LIMIT 1) AS communicated_date,
                   EXISTS(SELECT 1 FROM planning.impact_items impact WHERE impact.organization_id=p.organization_id
                     AND impact.schedule_solution_id=pv.schedule_solution_id AND impact.project_id=p.id
                     AND impact.impact_kind='COMMUNICATION_RECOMMENDED') AS communication_recommended,
                   EXISTS(SELECT 1 FROM planning.planning_state_revisions r
                     JOIN planning.planning_state_revisions base ON base.organization_id=r.organization_id AND base.id=pv.planning_state_revision_id
                     WHERE r.organization_id=p.organization_id AND r.plant_id=p.plant_id AND r.revision_no>base.revision_no
                       AND r.change_summary @> jsonb_build_object('current_affected',true)) AS plan_requires_reconciliation
            FROM core.projects p JOIN core.customers c ON c.organization_id=p.organization_id AND c.id=p.customer_id
            JOIN core.project_priorities pp ON pp.organization_id=p.organization_id AND pp.id=p.priority_id
            JOIN core.plants pl ON pl.organization_id=p.organization_id AND pl.id=p.plant_id
            LEFT JOIN production.product_definition_revisions d ON d.organization_id=p.organization_id AND d.id=pl.current_product_definition_revision_id
            LEFT JOIN planning.plan_versions pv ON pv.organization_id=p.organization_id AND pv.id=pl.current_plan_version_id
            WHERE p.organization_id=:org AND p.plant_id=:plant
              AND (CAST(:status AS text) IS NULL OR p.status::text=CAST(:status AS text))
              AND (CAST(:priority AS text) IS NULL OR pp.code=CAST(:priority AS text))
              AND (CAST(:customer AS uuid) IS NULL OR p.customer_id=CAST(:customer AS uuid))
              AND (CAST(:from_date AS date) IS NULL OR p.committed_date>=CAST(:from_date AS date))
              AND (CAST(:to_date AS date) IS NULL OR p.committed_date<=CAST(:to_date AS date))
              AND lower(concat_ws(' ',p.code,p.name,c.display_name)) LIKE :search
            ORDER BY CASE p.status WHEN 'active' THEN 0 WHEN 'draft' THEN 1 WHEN 'inactive' THEN 2 ELSE 3 END,
                     pp.rank,p.committed_date NULLS LAST,p.code,p.id
        """), {"org":org,"plant":plant,"status":status,"priority":priority,"customer":customer_id,
                "from_date":committed_from,"to_date":committed_to,"search":"%"+search.lower()+"%"}).mappings().all()
        milestones = self.conn.execute(text("""
            SELECT DISTINCT ON (m.project_id,d.code) m.project_id,d.code,m.occurred_at,m.notes
            FROM core.project_milestones m JOIN core.milestone_definitions d
              ON d.organization_id=m.organization_id AND d.id=m.milestone_definition_id
            JOIN core.projects p ON p.organization_id=m.organization_id AND p.id=m.project_id
            WHERE m.organization_id=:org AND p.plant_id=:plant AND d.code IN ('MEASUREMENT','REPLANTEO')
              AND NOT EXISTS(SELECT 1 FROM core.project_milestones next WHERE next.organization_id=m.organization_id AND next.supersedes_id=m.id)
            ORDER BY m.project_id,d.code,m.created_at DESC,m.id DESC
        """), {"org":org,"plant":plant}).mappings().all()
        facts = {(r["project_id"],r["code"]):r for r in milestones}
        today = datetime.now(ZoneInfo(options["timezone"])).date()
        from production_besten.persistence.production_release_uow import PostgresProductionReleaseUnitOfWork
        readiness_uow = PostgresProductionReleaseUnitOfWork(self._engine)
        readiness_uow._connection = self.conn
        readiness_by_project = readiness_uow.readiness(org, plant)
        result=[]
        for row in rows:
            p={k:row[k] for k in ("id","plant_id","code","name","description","customer_id","customer_name","customer_email","customer_phone","priority_id","priority_code","status","committed_date","desired_start_at","row_version","lot_count","communicated_date","plan_requires_reconciliation","operation_ids","planned_operation_ids")}
            p.update({k:row[k] for k in ("installation_site_name","installation_address","installation_locality","installation_contact_name","installation_contact_phone","installation_access_notes")})
            p["operation_count"]=len(p["operation_ids"])
            p['production_readiness'] = readiness_by_project[p['id']]
            definition=next((item for item in (row["canonical_snapshot"] or {}).get("projects",[]) if item["code"]==p["code"]),None)
            defined=definition is not None
            released=bool(definition and any(op.get("phases") for group in [definition.get("unassigned_operations",[]),*(lot.get("operations",[]) for lot in definition.get("lots",[]))] for op in group))
            p["definition_revision_no"]=row["plant_revision_no"] if defined else None
            p["plannable"]=bool(readiness_by_project[p['id']]['eligible'])
            for field,kind in (("measurement","MEASUREMENT"),("replanteo","REPLANTEO")):
                fact=facts.get((p["id"],kind))
                p[field]={"supported":True,"occurred_at":fact["occurred_at"] if fact else None,"notes":fact["notes"] if fact else None}
            p["ready_for_definition"]=bool(p["name"].strip() and p["customer_id"] and p["committed_date"] and p["status"] in {"draft","active"})
            p["estimated_date"]=row["estimated_at"].astimezone(ZoneInfo(options["timezone"])).date() if row["estimated_at"] else None
            p["overdue"]=bool(p["committed_date"] and (p["estimated_date"] or today)>p["committed_date"] and p["status"] not in {"archived","inactive"})
            # Keep the established communication rule's recommendations as facts;
            # project edits never create or send a communication.
            p["communication_recommended"]=row["communication_recommended"]
            result.append(p)
        return result

    def project_detail(self, org, plant, project):
        rows=self.list_projects(org,plant)
        value=next((row for row in rows if row["id"]==project),None)
        if value is None:
            raise EntityNotFound()
        return value

    def execute_intake(self, command):
        c=command
        org,plant=c.organization_id,c.plant_id
        # Catalog and project writes share a deterministic organization/plant order.
        if not self.conn.scalar(text("SELECT id FROM core.organizations WHERE id=:org AND status='active' FOR UPDATE"),{"org":org}):
            raise EntityNotFound()
        self._lock_plant(org,plant)
        self._require_actor(org,c.actor_id)
        self.conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),{"key":str(c.command_id)})
        digest=hashlib.sha256(json.dumps({"org":str(org),"plant":str(plant),"actor":str(c.actor_id),"action":c.action,"project":str(c.project_id),"version":c.expected_row_version,"payload":c.payload},default=str,sort_keys=True).encode()).hexdigest()
        replay=self.conn.execute(text("SELECT metadata,after_data FROM audit.audit_entries WHERE organization_id=:org AND request_id=:key ORDER BY created_at LIMIT 1"),{"org":org,"key":c.command_id}).mappings().one_or_none()
        if replay:
            if replay["metadata"].get("project_intake_hash")!=digest:
                raise IdempotencyConflict("La clave corresponde a otra intención o contexto.")
            return {**replay["after_data"],"idempotent_replay":True}
        before=None
        payload=c.payload
        if c.action=="create_customer":
            if not payload['display_name'].strip():
                raise InvalidProductDefinition('El nombre del cliente es obligatorio.')
            identifier=uuid4()
            customer=dict(self.conn.execute(text("""INSERT INTO core.customers(id,organization_id,display_name,phone,email)
                VALUES (:id,:org,:name,:phone,:email) RETURNING id,display_name,phone,email"""),
                {'id':identifier,'org':org,'name':payload['display_name'].strip(),'phone':payload.get('phone'),'email':payload.get('email')}).mappings().one())
        elif c.action=="create":
            if payload.get("status","draft")!="draft":
                raise InvalidProductDefinition("El proyecto nuevo comienza como borrador.")
            result=self.create_project(CreateProject(org,plant,payload["customer_id"],payload["priority_id"],payload["code"],payload["name"],c.actor_id,
                payload.get("description"),payload.get("committed_date"),payload.get("desired_start_at")))
            identifier=result.entity_id
        else:
            before=self.conn.execute(text("SELECT * FROM core.projects WHERE organization_id=:org AND plant_id=:plant AND id=:id FOR UPDATE"),{"org":org,"plant":plant,"id":c.project_id}).mappings().one_or_none()
            if before is None:raise EntityNotFound()
            identifier=before["id"]
            if before["row_version"]!=c.expected_row_version:
                raise ProjectIntakeVersionConflict("El proyecto cambió desde que lo abriste. Actualizá la información antes de guardar.")
            if before["status"]=="archived":raise ProductDefinitionConflict("El proyecto archivado conserva su historia y no puede editarse.")
            if c.action=="update":
                self._require_owned("core.customers",org,payload["customer_id"],"customer")
                self._require_owned("core.project_priorities",org,payload["priority_id"],"priority")
                if not payload["name"].strip():raise InvalidProductDefinition("El nombre es obligatorio.")
                self.conn.execute(text("""UPDATE core.projects SET name=:name,description=:description,customer_id=:customer,
                    priority_id=:priority,committed_date=:committed,updated_at=now(),row_version=row_version+1
                    WHERE organization_id=:org AND id=:id"""),{"name":payload["name"].strip(),"description":payload.get("description"),"customer":payload["customer_id"],"priority":payload["priority_id"],"committed":payload.get("committed_date"),"org":org,"id":identifier})
            elif c.action=="location":
                fields=("installation_site_name","installation_address","installation_locality","installation_contact_name","installation_contact_phone","installation_access_notes")
                values={k:(payload.get(k) or '').strip() or None for k in fields}
                assignments=','.join(k+'=:'+k for k in fields)
                self.conn.execute(text('UPDATE core.projects SET '+assignments+',updated_at=now(),row_version=row_version+1 WHERE organization_id=:org AND id=:id'),values|{'org':org,'id':identifier})
            elif c.action=="complete":
                self.conn.execute(text('SELECT id FROM production.required_operations WHERE organization_id=:org AND project_id=:id ORDER BY id FOR UPDATE'),{'org':org,'id':identifier})
                from production_besten.persistence.installation_queries import project_completion
                if not project_completion(self.conn,org,plant,identifier):
                    raise ProductDefinitionConflict('No se puede cerrar: quedan operaciones obligatorias pendientes o falta definición congelada.')
                self.conn.execute(text("UPDATE core.projects SET status='archived',closed_at=now(),updated_at=now(),row_version=row_version+1 WHERE organization_id=:org AND id=:id"),{'org':org,'id':identifier})
            elif c.action=="status":
                allowed={"draft":{"active","archived"},"active":{"inactive","archived"},"inactive":{"active","archived"}}
                if payload["status"] not in allowed.get(before["status"],set()):raise ProductDefinitionConflict("Transición de estado no permitida.")
                if payload["status"] in {"inactive","archived"} and self.conn.scalar(text("""SELECT EXISTS(SELECT 1 FROM execution.operation_executions e JOIN production.required_operations o ON o.organization_id=e.organization_id AND o.id=e.required_operation_id WHERE e.organization_id=:org AND o.project_id=:id AND e.status IN ('running','paused'))"""),{"org":org,"id":identifier}):
                    raise ProductDefinitionConflict("El proyecto tiene ejecución en curso; no se puede suspender ni archivar.")
                self.conn.execute(text("UPDATE core.projects SET status=CAST(:status AS core.record_status),closed_at=CASE WHEN CAST(:status AS text)='archived' THEN now() ELSE closed_at END,updated_at=now(),row_version=row_version+1 WHERE organization_id=:org AND id=:id"),{"status":payload["status"],"org":org,"id":identifier})
            elif c.action in {"measurement","replanteo"}:
                self._register_milestone(c,identifier)
                self.conn.execute(text("UPDATE core.projects SET updated_at=now(),row_version=row_version+1 WHERE organization_id=:org AND id=:id"),{"org":org,"id":identifier})
            else:raise InvalidProductDefinition("Comando de proyecto no soportado.")
            relevant=c.action in {"status","measurement","replanteo","location","complete"} or (c.action=="update" and any(str(before[key])!=str(payload.get(key)) for key in ("priority_id","committed_date")))
            if relevant:self._advance_intake_state(c,identifier)
        after=({'customer':customer,'idempotent_replay':False} if c.action=='create_customer'
               else {"project":self.project_detail(org,plant,identifier),"idempotent_replay":False})
        self.conn.execute(text("""INSERT INTO audit.audit_entries (organization_id,actor_user_id,action_code,entity_type,entity_id,request_id,transaction_key,before_data,after_data,metadata)
            VALUES (:org,:actor,:action,:entity,:id,:key,:key,CAST(:before AS jsonb),CAST(:after AS jsonb),CAST(:metadata AS jsonb))"""),
            {"org":org,"actor":c.actor_id,"action":"PROJECT_INTAKE_"+c.action.upper(),"entity":"customer" if c.action=='create_customer' else "project","id":identifier,"key":c.command_id,"before":json.dumps(dict(before),default=str) if before else None,"after":json.dumps(after,default=str),"metadata":json.dumps({"project_intake_hash":digest,"plant_id":str(plant),"dev_only":True})})
        if self._failpoint=="after_intake":raise RuntimeError("intake rollback probe")
        return after

    def _register_milestone(self,c,identifier):
        occurred=c.payload["occurred_at"]
        if occurred.tzinfo is None or occurred.utcoffset() is None or occurred>datetime.now(timezone.utc):
            raise InvalidProductDefinition("El hito debe registrar una fecha realizada con zona horaria; no una fecha prevista futura.")
        code={"measurement":"MEASUREMENT","replanteo":"REPLANTEO"}[c.action]
        definition=self.conn.scalar(text("SELECT id FROM core.milestone_definitions WHERE organization_id=:org AND code=:code AND status='active'"),{"org":c.organization_id,"code":code})
        if definition is None:
            definition=uuid4()
            self.conn.execute(text("""INSERT INTO core.milestone_definitions(id,organization_id,code,name,category,sequence_no)
                SELECT :id,:org,:code,:name,'intake',COALESCE(max(sequence_no),0)+1 FROM core.milestone_definitions WHERE organization_id=:org"""),
                {"id":definition,"org":c.organization_id,"code":code,"name":"Medición" if c.action=="measurement" else "Replanteo"})
        previous=self.conn.scalar(text("""SELECT m.id FROM core.project_milestones m WHERE m.organization_id=:org AND m.project_id=:project AND m.milestone_definition_id=:definition
            AND NOT EXISTS(SELECT 1 FROM core.project_milestones s WHERE s.organization_id=m.organization_id AND s.supersedes_id=m.id)
            ORDER BY m.created_at DESC,m.id DESC LIMIT 1"""),{"org":c.organization_id,"project":identifier,"definition":definition})
        self.conn.execute(text("INSERT INTO core.project_milestones(organization_id,project_id,milestone_definition_id,occurred_at,notes,supersedes_id) VALUES (:org,:project,:definition,:occurred,:notes,:previous)"),
            {"org":c.organization_id,"project":identifier,"definition":definition,"occurred":occurred,"notes":c.payload.get("notes"),"previous":previous})

    def _advance_intake_state(self,c,identifier):
        head=self.conn.execute(text("SELECT current_revision_no FROM planning.planning_state_heads WHERE organization_id=:org AND plant_id=:plant FOR UPDATE"),{"org":c.organization_id,"plant":c.plant_id}).mappings().one_or_none()
        if head is None:return
        affected=bool(self.conn.scalar(text("""SELECT EXISTS(SELECT 1 FROM core.plants p JOIN planning.plan_versions pv ON pv.organization_id=p.organization_id AND pv.id=p.current_plan_version_id
            JOIN planning.operation_plan_results r ON r.organization_id=p.organization_id AND r.schedule_solution_id=pv.schedule_solution_id
            JOIN production.required_operations o ON o.organization_id=r.organization_id AND o.id=r.required_operation_id
            WHERE p.organization_id=:org AND p.id=:plant AND o.project_id=:project)"""),{"org":c.organization_id,"plant":c.plant_id,"project":identifier}))
        revision=uuid4()
        self.conn.execute(text("""INSERT INTO planning.planning_state_revisions(id,organization_id,plant_id,revision_no,reason,transaction_key,change_summary,created_by)
            VALUES (:id,:org,:plant,:number,'PROJECT_INTAKE_CHANGED',:key,CAST(:summary AS jsonb),:actor)"""),{"id":revision,"org":c.organization_id,"plant":c.plant_id,"number":head["current_revision_no"]+1,"key":c.command_id,"actor":c.actor_id,"summary":json.dumps({"project_id":str(identifier),"current_affected":affected,"action":c.action})})
        self.conn.execute(text("UPDATE planning.planning_state_heads SET current_revision_id=:id,current_revision_no=current_revision_no+1,row_version=row_version+1,updated_at=now(),updated_by=:actor WHERE organization_id=:org AND plant_id=:plant"),{"id":revision,"org":c.organization_id,"plant":c.plant_id,"actor":c.actor_id})
        self.conn.execute(text("UPDATE planning.scenarios SET status='stale',updated_at=now(),row_version=row_version+1 WHERE organization_id=:org AND plant_id=:plant AND status IN ('draft','calculating','ready')"),{"org":c.organization_id,"plant":c.plant_id})


class PostgresProjectIntakeUnitOfWorkFactory:
    def __init__(self,engine,*,failpoint=None):
        self.engine,self.failpoint=engine,failpoint

    def __call__(self):
        return PostgresProjectIntakeUnitOfWork(self.engine,failpoint=self.failpoint)
