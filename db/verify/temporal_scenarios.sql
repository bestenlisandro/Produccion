\set ON_ERROR_STOP on

BEGIN;

INSERT INTO core.organizations(id,slug,legal_name,display_name,default_timezone)
VALUES ('10000000-0000-0000-0000-000000000001','verify-org-1','Verify Org 1','Verify Org 1','America/Buenos_Aires'),
       ('20000000-0000-0000-0000-000000000001','verify-org-2','Verify Org 2','Verify Org 2','America/Buenos_Aires');

INSERT INTO core.user_profiles(id,organization_id,auth_subject,display_name)
VALUES ('10000000-0000-0000-0000-000000000002','10000000-0000-0000-0000-000000000001','verify-user-1','Verifier 1'),
       ('20000000-0000-0000-0000-000000000002','20000000-0000-0000-0000-000000000001','verify-user-2','Verifier 2');

INSERT INTO capacity.calendars(id,organization_id,code,name,timezone,calendar_kind)
VALUES ('10000000-0000-0000-0000-000000000003','10000000-0000-0000-0000-000000000001','BASE','Base','America/Buenos_Aires','working'),
       ('20000000-0000-0000-0000-000000000003','20000000-0000-0000-0000-000000000001','BASE','Base','America/Buenos_Aires','working');

INSERT INTO core.plants(id,organization_id,code,name,timezone,base_calendar_id)
VALUES ('10000000-0000-0000-0000-000000000004','10000000-0000-0000-0000-000000000001','P1','Plant 1','America/Buenos_Aires','10000000-0000-0000-0000-000000000003'),
       ('20000000-0000-0000-0000-000000000004','20000000-0000-0000-0000-000000000001','P2','Plant 2','America/Buenos_Aires','20000000-0000-0000-0000-000000000003');

INSERT INTO core.customers(id,organization_id,code,display_name)
VALUES ('10000000-0000-0000-0000-000000000005','10000000-0000-0000-0000-000000000001','C1','Customer 1'),
       ('20000000-0000-0000-0000-000000000005','20000000-0000-0000-0000-000000000001','C2','Customer 2');
INSERT INTO core.project_priorities(id,organization_id,code,name,rank,is_default)
VALUES ('10000000-0000-0000-0000-000000000006','10000000-0000-0000-0000-000000000001','NORMAL','Normal',1,true),
       ('20000000-0000-0000-0000-000000000006','20000000-0000-0000-0000-000000000001','NORMAL','Normal',1,true);

INSERT INTO core.projects(id,organization_id,plant_id,customer_id,code,name,priority_id,status)
VALUES ('10000000-0000-0000-0000-000000000007','10000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000004','10000000-0000-0000-0000-000000000005','PR1','Project 1','10000000-0000-0000-0000-000000000006','active');
INSERT INTO core.project_lots(id,organization_id,project_id,code,name,sequence_no,status)
VALUES ('10000000-0000-0000-0000-000000000008','10000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000007','L1','Lot 1',1,'active');

INSERT INTO capacity.work_centers(id,organization_id,plant_id,code,name,capacity_mode,base_calendar_id)
VALUES ('10000000-0000-0000-0000-000000000009','10000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000004','WC','Work Center','exclusive','10000000-0000-0000-0000-000000000003');
INSERT INTO capacity.skills(id,organization_id,code,name) VALUES ('10000000-0000-0000-0000-000000000010','10000000-0000-0000-0000-000000000001','ASSEMBLY','Assembly');
INSERT INTO capacity.employees(id,organization_id,plant_id,code,display_name,default_work_center_id,base_calendar_id)
VALUES ('10000000-0000-0000-0000-000000000011','10000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000004','E1','Employee 1','10000000-0000-0000-0000-000000000009','10000000-0000-0000-0000-000000000003');
INSERT INTO capacity.physical_resource_types(id,organization_id,code,name,resource_kind,default_scheduling_mode)
VALUES ('10000000-0000-0000-0000-000000000012','10000000-0000-0000-0000-000000000001','BENCH','Bench','bench','exclusive');
INSERT INTO capacity.physical_resources(id,organization_id,plant_id,work_center_id,resource_type_id,code,name,scheduling_mode,capacity_units,base_calendar_id)
VALUES ('10000000-0000-0000-0000-000000000013','10000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000004','10000000-0000-0000-0000-000000000009','10000000-0000-0000-0000-000000000012','B1','Bench 1','exclusive',1,'10000000-0000-0000-0000-000000000003');

INSERT INTO production.operation_definitions(id,organization_id,code,name,category)
VALUES ('10000000-0000-0000-0000-000000000014','10000000-0000-0000-0000-000000000001','ASSEMBLY','Assembly','assembly');
INSERT INTO production.required_operations(id,organization_id,project_id,project_lot_id,operation_definition_id,code,name,status)
VALUES ('10000000-0000-0000-0000-000000000015','10000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000007','10000000-0000-0000-0000-000000000008','10000000-0000-0000-0000-000000000014','OP1','Assembly','active');
INSERT INTO production.required_operation_phases(id,organization_id,required_operation_id,sequence_no,code,name,estimate_kind,original_estimate_minutes,split_policy,status)
VALUES ('10000000-0000-0000-0000-000000000016','10000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000015',1,'PH1','Assembly phase','labor_work',120,'splittable','active');

INSERT INTO production.product_definition_revisions(id,organization_id,plant_id,revision_no,snapshot_schema_version,canonicalization_version,canonical_snapshot,snapshot_sha256)
VALUES ('10000000-0000-0000-0000-000000000017','10000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000004',1,1,1,'{}',digest('{}','sha256'));
INSERT INTO planning.planning_state_revisions(id,organization_id,plant_id,revision_no,reason,transaction_key)
VALUES ('10000000-0000-0000-0000-000000000018','10000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000004',1,'verification','10000000-0000-0000-0000-000000000019');
INSERT INTO planning.planning_state_heads(plant_id,organization_id,current_revision_id,current_revision_no)
VALUES ('10000000-0000-0000-0000-000000000004','10000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000018',1);

INSERT INTO planning.scenarios(id,organization_id,plant_id,scenario_kind,base_state_revision_id,base_product_definition_revision_id,code,name,status,horizon_range,requested_by)
VALUES ('10000000-0000-0000-0000-000000000020','10000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000004','initial','10000000-0000-0000-0000-000000000018','10000000-0000-0000-0000-000000000017','S18','Scenario 18','ready','[2026-09-01 00:00-03,2026-09-10 00:00-03)','10000000-0000-0000-0000-000000000002'),
       ('10000000-0000-0000-0000-000000000021','10000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000004','initial','10000000-0000-0000-0000-000000000018','10000000-0000-0000-0000-000000000017','S19','Scenario 19','ready','[2026-09-01 00:00-03,2026-09-10 00:00-03)','10000000-0000-0000-0000-000000000002');
INSERT INTO planning.schedule_solutions(id,organization_id,scenario_id,run_no,status,algorithm_version,input_product_definition_revision_id,base_state_revision_id,input_snapshot,input_sha256,started_at,finished_at,horizon_range,solution_sha256,ready_at)
VALUES ('10000000-0000-0000-0000-000000000022','10000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000020',1,'ready','verify-1','10000000-0000-0000-0000-000000000017','10000000-0000-0000-0000-000000000018','{}',digest('input-18','sha256'),now(),now(),'[2026-09-01 00:00-03,2026-09-10 00:00-03)',digest('solution-18','sha256'),now()),
       ('10000000-0000-0000-0000-000000000023','10000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000021',1,'ready','verify-1','10000000-0000-0000-0000-000000000017','10000000-0000-0000-0000-000000000018','{}',digest('input-19','sha256'),now(),now(),'[2026-09-01 00:00-03,2026-09-10 00:00-03)',digest('solution-19','sha256'),now());

INSERT INTO planning.operation_plan_results(id,organization_id,schedule_solution_id,required_operation_id,result_status,planned_start_at,planned_end_at)
VALUES ('10000000-0000-0000-0000-000000000024','10000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000022','10000000-0000-0000-0000-000000000015','planned','2026-09-01 10:00-03','2026-09-01 12:00-03'),
       ('10000000-0000-0000-0000-000000000025','10000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000023','10000000-0000-0000-0000-000000000015','planned','2026-09-01 10:00-03','2026-09-01 12:00-03');
INSERT INTO planning.phase_plan_results(id,organization_id,operation_plan_result_id,schedule_solution_id,required_operation_phase_id,result_status,planned_work_minutes)
VALUES ('10000000-0000-0000-0000-000000000026','10000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000024','10000000-0000-0000-0000-000000000022','10000000-0000-0000-0000-000000000016','planned',120),
       ('10000000-0000-0000-0000-000000000027','10000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000025','10000000-0000-0000-0000-000000000023','10000000-0000-0000-0000-000000000016','planned',120);
INSERT INTO planning.planned_phase_assignments(id,organization_id,phase_plan_result_id,schedule_solution_id,assignment_kind,planned_start_at,planned_end_at,work_minutes)
VALUES ('10000000-0000-0000-0000-000000000028','10000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000026','10000000-0000-0000-0000-000000000022','direct','2026-09-01 10:00-03','2026-09-01 12:00-03',120),
       ('10000000-0000-0000-0000-000000000029','10000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000027','10000000-0000-0000-0000-000000000023','direct','2026-09-01 10:00-03','2026-09-01 12:00-03',120);
INSERT INTO planning.assignment_segments(id,organization_id,planned_phase_assignment_id,schedule_solution_id,segment_no,time_range,normal_minutes,work_minutes)
VALUES ('10000000-0000-0000-0000-000000000030','10000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000028','10000000-0000-0000-0000-000000000022',1,'[2026-09-01 10:00-03,2026-09-01 12:00-03)',120,120),
       ('10000000-0000-0000-0000-000000000031','10000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000029','10000000-0000-0000-0000-000000000023',1,'[2026-09-01 10:00-03,2026-09-01 12:00-03)',120,120);

-- Same employee/resource and time are valid because the solutions differ.
INSERT INTO planning.human_segment_assignments(organization_id,assignment_segment_id,schedule_solution_id,employee_id,time_range,normal_minutes,work_minutes)
VALUES ('10000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000030','10000000-0000-0000-0000-000000000022','10000000-0000-0000-0000-000000000011','[2026-09-01 10:00-03,2026-09-01 12:00-03)',120,120),
       ('10000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000031','10000000-0000-0000-0000-000000000023','10000000-0000-0000-0000-000000000011','[2026-09-01 10:00-03,2026-09-01 12:00-03)',120,120);
INSERT INTO planning.physical_resource_reservations(organization_id,assignment_segment_id,schedule_solution_id,physical_resource_id,time_range,capacity_units,exclusive_guard,usage_mode)
VALUES ('10000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000030','10000000-0000-0000-0000-000000000022','10000000-0000-0000-0000-000000000013','[2026-09-01 10:00-03,2026-09-01 12:00-03)',1,true,'active_use'),
       ('10000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000031','10000000-0000-0000-0000-000000000023','10000000-0000-0000-0000-000000000013','[2026-09-01 10:00-03,2026-09-01 12:00-03)',1,true,'active_use');

-- Same-solution overlapping exclusive reservation must fail.
INSERT INTO planning.assignment_segments(id,organization_id,planned_phase_assignment_id,schedule_solution_id,segment_no,time_range,normal_minutes,work_minutes)
VALUES ('10000000-0000-0000-0000-000000000032','10000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000028','10000000-0000-0000-0000-000000000022',2,'[2026-09-01 11:00-03,2026-09-01 13:00-03)',120,120);
DO $$
BEGIN
  BEGIN
    INSERT INTO planning.physical_resource_reservations(organization_id,assignment_segment_id,schedule_solution_id,physical_resource_id,time_range,capacity_units,exclusive_guard,usage_mode)
    VALUES ('10000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000032','10000000-0000-0000-0000-000000000022','10000000-0000-0000-0000-000000000013','[2026-09-01 11:00-03,2026-09-01 13:00-03)',1,true,'active_use');
    RAISE EXCEPTION 'Expected exclusion_violation for same-solution resource overlap';
  EXCEPTION WHEN exclusion_violation THEN NULL;
  END;
END $$;

-- Same-solution overlapping employee assignment must also fail.
DO $$
BEGIN
  BEGIN
    INSERT INTO planning.human_segment_assignments(organization_id,assignment_segment_id,schedule_solution_id,employee_id,time_range,normal_minutes,work_minutes)
    VALUES ('10000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000032','10000000-0000-0000-0000-000000000022','10000000-0000-0000-0000-000000000011','[2026-09-01 11:00-03,2026-09-01 13:00-03)',120,120);
    RAISE EXCEPTION 'Expected exclusion_violation for same-solution employee overlap';
  EXCEPTION WHEN exclusion_violation THEN NULL;
  END;
END $$;

-- Adjacent [start,end) ranges are compatible at the shared 12:00 boundary.
INSERT INTO planning.assignment_segments(id,organization_id,planned_phase_assignment_id,schedule_solution_id,segment_no,time_range,normal_minutes,work_minutes)
VALUES ('10000000-0000-0000-0000-000000000034','10000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000028','10000000-0000-0000-0000-000000000022',3,'[2026-09-01 12:00-03,2026-09-01 13:00-03)',60,60);
INSERT INTO planning.human_segment_assignments(organization_id,assignment_segment_id,schedule_solution_id,employee_id,time_range,normal_minutes,work_minutes)
VALUES ('10000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000034','10000000-0000-0000-0000-000000000022','10000000-0000-0000-0000-000000000011','[2026-09-01 12:00-03,2026-09-01 13:00-03)',60,60);
INSERT INTO planning.physical_resource_reservations(organization_id,assignment_segment_id,schedule_solution_id,physical_resource_id,time_range,capacity_units,exclusive_guard,usage_mode)
VALUES ('10000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000034','10000000-0000-0000-0000-000000000022','10000000-0000-0000-0000-000000000013','[2026-09-01 12:00-03,2026-09-01 13:00-03)',1,true,'active_use');

-- Physical occupation may cross midnight without generating labor work.
-- The same nocturnal occupation is valid in two alternative solutions.
INSERT INTO planning.physical_occupations(id,organization_id,schedule_solution_id,project_lot_id,required_operation_phase_id,physical_resource_id,source_kind,time_range,planned_release_at,is_effective)
VALUES ('10000000-0000-0000-0000-000000000035','10000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000022','10000000-0000-0000-0000-000000000008','10000000-0000-0000-0000-000000000016','10000000-0000-0000-0000-000000000013','planned','[2026-09-01 22:00-03,2026-09-02 06:00-03)','2026-09-02 06:00-03',true),
       ('10000000-0000-0000-0000-000000000036','10000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000023','10000000-0000-0000-0000-000000000008','10000000-0000-0000-0000-000000000016','10000000-0000-0000-0000-000000000013','planned','[2026-09-01 22:00-03,2026-09-02 06:00-03)','2026-09-02 06:00-03',true);
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM planning.physical_occupations
     WHERE id='10000000-0000-0000-0000-000000000035'
       AND lower_inc(time_range) AND NOT upper_inc(time_range)
       AND upper(time_range)-lower(time_range)=interval '8 hours'
  ) THEN RAISE EXCEPTION 'Nocturnal physical occupation or [start,end) semantics were not preserved'; END IF;
  BEGIN
    INSERT INTO planning.physical_occupations(organization_id,schedule_solution_id,project_lot_id,physical_resource_id,source_kind,time_range,is_effective)
    VALUES ('10000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000022','10000000-0000-0000-0000-000000000008','10000000-0000-0000-0000-000000000013','planned','[2026-09-02 05:00-03,2026-09-02 07:00-03)',true);
    RAISE EXCEPTION 'Expected exclusion_violation for same-solution physical occupation overlap';
  EXCEPTION WHEN exclusion_violation THEN NULL;
  END;
END $$;

-- Cross-organization reference must fail at the composite FK.
DO $$
BEGIN
  BEGIN
    INSERT INTO core.projects(organization_id,plant_id,customer_id,code,name,priority_id,status)
    VALUES ('20000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000004','20000000-0000-0000-0000-000000000005','BAD','Cross tenant','20000000-0000-0000-0000-000000000006','active');
    RAISE EXCEPTION 'Expected foreign_key_violation for cross-organization plant';
  EXCEPTION WHEN foreign_key_violation THEN NULL;
  END;
END $$;

-- A new product revision preserves the historical snapshot.
INSERT INTO production.product_definition_revisions(id,organization_id,plant_id,revision_no,parent_revision_id,snapshot_schema_version,canonicalization_version,canonical_snapshot,snapshot_sha256)
VALUES ('10000000-0000-0000-0000-000000000033','10000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000004',2,'10000000-0000-0000-0000-000000000017',1,1,'{"revision":2}',digest('{"revision":2}','sha256'));
DO $$
BEGIN
  IF (SELECT canonical_snapshot FROM production.product_definition_revisions WHERE id='10000000-0000-0000-0000-000000000017') <> '{}'::jsonb THEN
    RAISE EXCEPTION 'Historical snapshot was modified';
  END IF;
  BEGIN
    INSERT INTO production.product_definition_revisions(organization_id,plant_id,revision_no,snapshot_schema_version,canonicalization_version,canonical_snapshot,snapshot_sha256)
    VALUES ('10000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000004',2,1,1,'{"duplicate":true}',digest('{"duplicate":true}','sha256'));
    RAISE EXCEPTION 'Expected unique_violation for duplicate product definition revision number';
  EXCEPTION WHEN unique_violation THEN NULL;
  END;
END $$;

-- Minimum trigger functions reject internally inconsistent references.
INSERT INTO core.projects(id,organization_id,plant_id,customer_id,code,name,priority_id,status)
VALUES ('10000000-0000-0000-0000-000000000038','10000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000004','10000000-0000-0000-0000-000000000005','PR2','Project 2','10000000-0000-0000-0000-000000000006','active');
DO $$
BEGIN
  BEGIN
    INSERT INTO production.required_operations(organization_id,project_id,project_lot_id,operation_definition_id,code,name,status)
    VALUES ('10000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000038','10000000-0000-0000-0000-000000000008','10000000-0000-0000-0000-000000000014','BAD-LOT','Invalid lot ownership','active');
    RAISE EXCEPTION 'Expected check_violation for project/lot mismatch';
  EXCEPTION WHEN check_violation THEN NULL;
  END;
  BEGIN
    INSERT INTO production.installation_lot_coverages(organization_id,installation_operation_id,project_lot_id,coverage_percent)
    VALUES ('10000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000015','10000000-0000-0000-0000-000000000008',100);
    RAISE EXCEPTION 'Expected check_violation for non-installation operation coverage';
  EXCEPTION WHEN check_violation THEN NULL;
  END;
END $$;

-- PlanningStateRevision advances monotonically and is reflected by the plant head.
INSERT INTO planning.planning_state_revisions(id,organization_id,plant_id,revision_no,reason,transaction_key,change_summary)
VALUES ('10000000-0000-0000-0000-000000000040','10000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000004',2,'remaining estimate initialized','10000000-0000-0000-0000-000000000140','{"remaining_estimate":1}');
INSERT INTO planning.effective_events(id,organization_id,plant_id,event_type_code,payload_schema_version,occurred_at,effective_at,entity_type,entity_id,payload,planning_state_revision_id,source_system,external_reference)
VALUES ('10000000-0000-0000-0000-000000000041','10000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000004','REMAINING_ESTIMATE_UPDATED',1,'2026-09-01 11:00-03','2026-09-01 11:00-03','operation_execution','10000000-0000-0000-0000-000000000042','{"remaining_minutes":90}','10000000-0000-0000-0000-000000000040','verification','remaining-1');
UPDATE planning.planning_state_heads
   SET current_revision_id='10000000-0000-0000-0000-000000000040',current_revision_no=2,row_version=row_version+1
 WHERE plant_id='10000000-0000-0000-0000-000000000004';
DO $$
BEGIN
  BEGIN
    INSERT INTO planning.planning_state_revisions(organization_id,plant_id,revision_no,reason,transaction_key)
    VALUES ('10000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000004',2,'duplicate','10000000-0000-0000-0000-000000000141');
    RAISE EXCEPTION 'Expected unique_violation for duplicate planning state revision';
  EXCEPTION WHEN unique_violation THEN NULL;
  END;
  BEGIN
    INSERT INTO planning.schedule_solutions(organization_id,scenario_id,run_no,status,algorithm_version,input_product_definition_revision_id,base_state_revision_id,input_snapshot,input_sha256,started_at,horizon_range)
    VALUES ('10000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000020',2,'calculating','invalid-base','10000000-0000-0000-0000-000000000017','10000000-0000-0000-0000-000000000040','{}',digest('invalid-base','sha256'),now(),'[2026-09-01 00:00-03,2026-09-10 00:00-03)');
    RAISE EXCEPTION 'Expected check_violation for solution/scenario revision mismatch';
  EXCEPTION WHEN check_violation THEN NULL;
  END;
END $$;

-- Execution freezes the original estimate and actual work remains append-only.
INSERT INTO execution.operation_executions(id,organization_id,required_operation_id,source_product_definition_revision_id,original_estimate_snapshot,status,started_at)
VALUES ('10000000-0000-0000-0000-000000000042','10000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000015','10000000-0000-0000-0000-000000000017','{"labor_minutes":120}','running','2026-09-01 10:00-03');
INSERT INTO execution.execution_segments(id,organization_id,operation_execution_id,required_operation_phase_id,segment_no,time_range,segment_kind,work_minutes,reason)
VALUES ('10000000-0000-0000-0000-000000000043','10000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000042','10000000-0000-0000-0000-000000000016',1,'[2026-09-01 10:00-03,2026-09-01 11:00-03)','work',60,NULL),
       ('10000000-0000-0000-0000-000000000044','10000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000042',NULL,2,'[2026-09-01 11:00-03,2026-09-01 11:30-03)','pause',0,'verification pause');
INSERT INTO execution.actual_resource_usages(id,organization_id,execution_segment_id,employee_id,time_range,work_minutes,usage_kind)
VALUES ('10000000-0000-0000-0000-000000000045','10000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000043','10000000-0000-0000-0000-000000000011','[2026-09-01 10:00-03,2026-09-01 11:00-03)',60,'labor');
DO $$
BEGIN
  BEGIN
    INSERT INTO execution.actual_resource_usages(organization_id,execution_segment_id,physical_resource_id,time_range,work_minutes,capacity_units,usage_kind)
    VALUES ('10000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000044','10000000-0000-0000-0000-000000000013','[2026-09-01 11:00-03,2026-09-01 11:30-03)',0,1,'occupation');
    RAISE EXCEPTION 'Expected check_violation for actual usage on pause segment';
  EXCEPTION WHEN check_violation THEN NULL;
  END;
END $$;

INSERT INTO production.operation_physical_requirements(id,organization_id,required_operation_phase_id,physical_resource_type_id,quantity,capacity_units,is_mandatory,usage_mode)
VALUES ('10000000-0000-0000-0000-000000000046','10000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000016','10000000-0000-0000-0000-000000000012',1,1,true,'active_use');
INSERT INTO execution.remaining_estimate_revisions(id,organization_id,operation_execution_id,revision_no,cutoff_at,input_mode,raw_input,reason,effective_event_id,planning_state_revision_id,executed_labor_minutes_at_cutoff,remaining_labor_minutes,updated_total_labor_minutes)
VALUES ('10000000-0000-0000-0000-000000000047','10000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000042',1,'2026-09-01 11:00-03','remaining_duration','{"minutes":90}','initial remaining estimate','10000000-0000-0000-0000-000000000041','10000000-0000-0000-0000-000000000040',60,90,150);
INSERT INTO execution.remaining_resource_estimates(id,organization_id,remaining_estimate_revision_id,required_operation_phase_id,dimension,skill_id,min_people,max_people,remaining_minutes)
VALUES ('10000000-0000-0000-0000-000000000049','10000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000047','10000000-0000-0000-0000-000000000016','LABOR_WORK','10000000-0000-0000-0000-000000000010',1,2,90);
INSERT INTO execution.remaining_resource_estimates(id,organization_id,remaining_estimate_revision_id,required_operation_phase_id,dimension,physical_requirement_id,remaining_minutes,capacity_units)
VALUES ('10000000-0000-0000-0000-000000000050','10000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000047','10000000-0000-0000-0000-000000000016','ACTIVE_PHYSICAL_USE','10000000-0000-0000-0000-000000000046',90,1);
INSERT INTO execution.remaining_resource_estimates(id,organization_id,remaining_estimate_revision_id,required_operation_phase_id,dimension,physical_resource_id,expected_release_at,capacity_units)
VALUES ('10000000-0000-0000-0000-000000000051','10000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000047','10000000-0000-0000-0000-000000000016','PHYSICAL_OCCUPATION','10000000-0000-0000-0000-000000000013','2026-09-02 06:00-03',1);
DO $$
BEGIN
  BEGIN
    INSERT INTO execution.remaining_estimate_revisions(organization_id,operation_execution_id,revision_no,cutoff_at,input_mode,raw_input,effective_event_id,planning_state_revision_id,executed_labor_minutes_at_cutoff,remaining_labor_minutes,updated_total_labor_minutes)
    VALUES ('10000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000042',2,'2026-09-01 11:30-03','remaining_duration','{"minutes":120}','10000000-0000-0000-0000-000000000041','10000000-0000-0000-0000-000000000040',60,120,999);
    RAISE EXCEPTION 'Expected check_violation for inconsistent updated total';
  EXCEPTION WHEN check_violation THEN NULL;
  END;
END $$;

-- A second remaining estimate is a new state revision; the previous row is superseded, never rewritten as history.
INSERT INTO planning.planning_state_revisions(id,organization_id,plant_id,revision_no,reason,transaction_key,change_summary)
VALUES ('10000000-0000-0000-0000-000000000052','10000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000004',3,'remaining estimate extended','10000000-0000-0000-0000-000000000152','{"remaining_estimate":2}');
INSERT INTO planning.effective_events(id,organization_id,plant_id,event_type_code,payload_schema_version,occurred_at,effective_at,entity_type,entity_id,payload,planning_state_revision_id,source_system,external_reference)
VALUES ('10000000-0000-0000-0000-000000000053','10000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000004','REMAINING_ESTIMATE_UPDATED',1,'2026-09-01 11:30-03','2026-09-01 11:30-03','operation_execution','10000000-0000-0000-0000-000000000042','{"remaining_minutes":120}','10000000-0000-0000-0000-000000000052','verification','remaining-2');
UPDATE planning.planning_state_heads
   SET current_revision_id='10000000-0000-0000-0000-000000000052',current_revision_no=3,row_version=row_version+1
 WHERE plant_id='10000000-0000-0000-0000-000000000004';
UPDATE execution.remaining_estimate_revisions
   SET superseded_at='2026-09-01 11:30-03',superseded_by_id='10000000-0000-0000-0000-000000000048'
 WHERE id='10000000-0000-0000-0000-000000000047';
INSERT INTO execution.remaining_estimate_revisions(id,organization_id,operation_execution_id,revision_no,previous_revision_id,cutoff_at,input_mode,raw_input,reason,effective_event_id,planning_state_revision_id,executed_labor_minutes_at_cutoff,remaining_labor_minutes,updated_total_labor_minutes)
VALUES ('10000000-0000-0000-0000-000000000048','10000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000042',2,'10000000-0000-0000-0000-000000000047','2026-09-01 11:30-03','remaining_duration','{"minutes":120}','extended by operator','10000000-0000-0000-0000-000000000053','10000000-0000-0000-0000-000000000052',60,120,180);
SET CONSTRAINTS ALL IMMEDIATE;
DO $$
DECLARE current_count integer;
BEGIN
  SELECT count(*) INTO current_count FROM execution.remaining_estimate_revisions
   WHERE operation_execution_id='10000000-0000-0000-0000-000000000042' AND superseded_at IS NULL;
  IF current_count <> 1 THEN RAISE EXCEPTION 'Expected exactly one current remaining estimate, got %', current_count; END IF;
  IF (SELECT id FROM execution.remaining_estimate_revisions WHERE operation_execution_id='10000000-0000-0000-0000-000000000042' AND superseded_at IS NULL) <> '10000000-0000-0000-0000-000000000048'::uuid THEN
    RAISE EXCEPTION 'The second remaining estimate did not become current';
  END IF;
  IF (SELECT original_estimate_snapshot FROM execution.operation_executions WHERE id='10000000-0000-0000-0000-000000000042') <> '{"labor_minutes":120}'::jsonb THEN
    RAISE EXCEPTION 'Original execution estimate was modified';
  END IF;
  IF (SELECT current_revision_no FROM planning.planning_state_heads WHERE plant_id='10000000-0000-0000-0000-000000000004') <> 3 THEN
    RAISE EXCEPTION 'Planning state head did not advance with remaining estimate update';
  END IF;
  BEGIN
    INSERT INTO execution.remaining_estimate_revisions(organization_id,operation_execution_id,revision_no,previous_revision_id,cutoff_at,input_mode,raw_input,effective_event_id,planning_state_revision_id,executed_labor_minutes_at_cutoff,remaining_labor_minutes,updated_total_labor_minutes)
    VALUES ('10000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000042',3,'10000000-0000-0000-0000-000000000048','2026-09-01 12:00-03','remaining_duration','{"minutes":100}','10000000-0000-0000-0000-000000000053','10000000-0000-0000-0000-000000000052',60,100,160);
    RAISE EXCEPTION 'Expected unique_violation for two current remaining estimates';
  EXCEPTION WHEN unique_violation THEN NULL;
  END;
END $$;

SELECT 'temporal_and_tenant_tests_passed' AS result;

ROLLBACK;
