import type {GanttData} from '../api/client'
import {ganttFixture,ganttScenarioFixture} from './fixtures'
export const ganttV2Fixture:GanttData={...ganttFixture,plant_name:'Vera Mujica',group_by:'project',
 range_from:'2026-10-26T03:00:00Z',range_to:'2026-11-02T03:00:00Z',
 groups:[{id:'project-v2',label:'A685 · Alacenas (fixture)',kind:'project'}],
 operations:['Corte Fondos','Multiple','Armado','Instalación'].map((name,i)=>({...ganttFixture.operations[0],
  operation_id:`op-${i}`,project_id:'project-v2',project_code:'A685',project_name:'Alacenas (fixture)',
  operation_name:name,operation_code:`OP${i}`,stage_name:['Corte','Procesado con Múltiple','Armado','Instalación'][i],stage_order:[2,4,6,9][i],operation_order:1,
  group_ids:['project-v2'],duration_minutes:[20,60,120,180][i],operational_status:i===2?'BLOQUEADO':'PENDIENTE',executed_minutes:0,actual_segments:[],
  split_policy:i<2?'non_splittable':'splittable',committed_date:'2026-10-27',skill_codes:[['CORTE_ESCUADRADORA','PERFORADORA_MULTIPLE','ARMADO','INSTALACION'][i]],
  planned_start:i<2?'2026-10-27T11:00:00Z':i===2?'2026-10-27T14:00:00Z':'2026-10-27T17:00:00Z',
  people:i===1?[{id:'person-3',name:'Mariano'}]:[{id:'person-1',name:'Gonzalo'},{id:'person-2',name:'Emiliano'}],
  resources:i===3?[]:[{...ganttFixture.operations[0].resources![0],name:['Escuadradora 1','Perforadora Múltiple 1','Banco 1'][i]}],
  centers:i===3?[]:[{...ganttFixture.operations[0].centers![0],name:['Escuadradora','Perforadora Múltiple','Armado'][i]}],
  planned_finish:i===0?'2026-10-27T11:20:00Z':i===1?'2026-10-27T12:00:00Z':i===2?'2026-10-27T16:45:00Z':'2026-10-27T20:00:00Z',
  planned_segments:i===2?[{started_at:'2026-10-27T14:00:00Z',ended_at:'2026-10-27T15:00:00Z',phase_name:'Trabajo'},{started_at:'2026-10-27T15:45:00Z',ended_at:'2026-10-27T16:45:00Z',phase_name:'Trabajo'}]:[],
  predecessors:i===2?[{id:'op-0',name:'Corte Fondos'},{id:'op-1',name:'Multiple'}]:i===3?[{id:'op-2',name:'Armado'}]:[],
  blocker_code:i===2?'PHYSICAL_RESOURCE_OCCUPIED':null,
 })),
 working_windows:[{started_at:'2026-10-27T11:00:00Z',ended_at:'2026-10-27T15:00:00Z',kind:'regular',label:'Mañana'},{started_at:'2026-10-27T15:45:00Z',ended_at:'2026-10-27T20:00:00Z',kind:'regular',label:'Tarde'}],
 occupations:[],scenario:null}
export const initialV2Fixture:GanttData={...ganttV2Fixture,plan_version_id:null,plan_version_number:null,scenario:{...ganttScenarioFixture.scenario!,scenario_kind:'initial',changed_operations:4,affected_projects:1,operations:[]}}
