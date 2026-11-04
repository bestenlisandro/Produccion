import type {GanttData} from '../api/client'
import {ganttV2Fixture} from './ganttV2Fixture'
import {ganttScenarioFixture} from './fixtures'

export const revisionSimulationId='00f1ae78-401d-4251-9413-4dd05cd0cc38'
const names=['Corte Fondos 3 mm','Procesado Múltiple 18 mm','Armado','Instalacion']
const starts=['2026-11-04T15:45:00Z','2026-11-04T15:45:00Z','2026-11-04T16:45:00Z','2026-11-04T18:45:00Z']
const finishes=['2026-11-04T16:05:00Z','2026-11-04T16:45:00Z','2026-11-04T18:45:00Z','2026-11-05T12:45:00Z']
export const revisionSimulationFixture:GanttData={...ganttV2Fixture,
 plan_version_number:1,range_from:'2026-11-02T03:00:00Z',range_to:'2026-11-09T03:00:00Z',
 operations:ganttV2Fixture.operations.map((o,i)=>({...o,operation_name:names[i],predecessors:o.predecessors?.map(p=>({...p,name:names[Number(p.id.split('-')[1])]}))})),
 available_scenarios:[{...ganttV2Fixture.available_scenarios[0],id:revisionSimulationId,scenario_kind:'simulation',name:'A685 REV 5',status:'ready',stale:false,expired:false,created_at:'2026-11-04T14:55:28Z'}],
 scenario:{...ganttScenarioFixture.scenario!,id:revisionSimulationId,name:'A685 REV 5',scenario_kind:'simulation',status:'ready',complete:true,stale:false,expired:false,
  changed_operations:4,affected_projects:1,operations:ganttV2Fixture.operations.map((o,i)=>({operation_id:o.operation_id,planned_start:starts[i],planned_finish:finishes[i],difference:'DELAYED',delta_minutes:11565}))},
}
