import { ganttFixture,ganttScenarioFixture } from './fixtures'
import type { GanttData } from '../api/client'

export const initialScenarioId=ganttScenarioFixture.scenario!.id
export const initialGanttFixture:GanttData={...ganttScenarioFixture,
  plan_version_id:null,plan_version_number:null,
  operations:ganttFixture.operations.map(o=>({...o,duration_minutes:120,predecessors:[]})),
  scenario:{...ganttScenarioFixture.scenario!,scenario_kind:'initial',complete:true},
}
