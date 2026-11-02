import type { GanttData } from '../api/client'

export const operation={operation_id:'11111111-1111-4111-8111-111111111111',project_id:'22222222-2222-4222-8222-222222222222',project_code:'P-1',project_name:'Cocina Pérez',lot_code:'L-1',lot_name:'Muebles bajos',operation_code:'ARM',operation_name:'Armado',phase_name:'Trabajo',planned_start:'2026-09-21T08:00:00Z',planned_finish:'2026-09-21T12:00:00Z',people:[{id:'33333333-3333-4333-8333-333333333333',name:'Operador Uno'}],work_center:'Armado',physical_resource:'Banco 1',priority:'Alta',priority_rank:1,operational_status:'EN_CURSO',progress_percent:70,executed_minutes:420,remaining_minutes:180,blocker_code:null}

export const ganttFixture: GanttData = {
  plan_version_id:'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', plan_version_number:6,
  planning_state_revision_id:'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
  timezone:'America/Argentina/Buenos_Aires', range_from:'2026-09-28T03:00:00Z',
  range_to:'2026-10-05T03:00:00Z', generated_at:'2026-09-29T13:00:00Z', group_by:'center',
  groups:[{id:'center-1',label:'Armado',kind:'center',capacity_mode:'cumulative',capacity:3}],
  operations:[{
    operation_id:operation.operation_id, project_id:operation.project_id,
    project_code:operation.project_code, project_name:operation.project_name,
    lot_code:operation.lot_code, lot_name:operation.lot_name, operation_code:operation.operation_code,
    operation_name:operation.operation_name, phase_id:'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
    phase_name:'Trabajo', planned_start:'2026-09-29T11:00:00Z', planned_finish:'2026-09-29T15:00:00Z',
    group_ids:['center-1'], people:[{id:'33333333-3333-4333-8333-333333333333',name:'Operador Uno'}],
    centers:[{id:'dddddddd-dddd-4ddd-8ddd-dddddddddddd',name:'Armado',capacity_mode:'cumulative',aggregate_capacity:3}],
    resources:[{id:'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee',name:'Banco 1',work_center_id:'dddddddd-dddd-4ddd-8ddd-dddddddddddd',scheduling_mode:'exclusive',capacity_units:1}],
    priority:'Alta',priority_rank:1,operational_status:'EN_CURSO',executed_minutes:60,remaining_minutes:180,
    blocker_code:null,actual_segments:[{id:'ffffffff-ffff-4fff-8fff-ffffffffffff',started_at:'2026-09-29T11:00:00Z',ended_at:'2026-09-29T12:00:00Z',work_minutes:60}],
  }],
  occupations:[{id:'12121212-1212-4121-8121-121212121212',project_name:'Cocina Pérez',lot_name:'Muebles bajos',resource_id:'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee',resource_name:'Banco 1',group_id:'center-1',started_at:'2026-09-29T11:00:00Z',ended_at:'2026-09-29T15:00:00Z',source_kind:'planned'}],
  working_windows:[{started_at:'2026-09-29T11:00:00Z',ended_at:'2026-09-29T20:00:00Z',kind:'regular',label:'Turno'}],
  available_scenarios:[{id:'13131313-1313-4131-8131-131313131313',code:'R-1',name:'Simulación R-1',scenario_kind:'replan',expired:false,status:'ready',stale:false,created_at:'2026-09-29T12:00:00Z'}],
  scenario:null,
}

export const ganttScenarioFixture: GanttData = {...ganttFixture, scenario:{
  expired:false,scenario_kind:'replan',complete:true,
  id:'13131313-1313-4131-8131-131313131313',code:'R-1',name:'Simulación R-1',status:'ready',stale:false,
  row_version:1,promotion_lock_version:2,changed_operations:1,affected_projects:1,customer_date_alerts:1,
  communication_recommended:true,project_finish_changes:[{project:'P-1'}],operations:[{
    operation_id:operation.operation_id,planned_start:'2026-09-29T12:00:00Z',planned_finish:'2026-09-29T16:00:00Z',difference:'DELAYED',delta_minutes:60,
  }],
}}
