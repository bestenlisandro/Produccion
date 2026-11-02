import {expect,test} from 'vitest'
import {ganttFixture,ganttScenarioFixture} from '../../test/fixtures'
import {confirmationBlocker,scenarioLabel} from './scenarioPresentation'

test.each([
 {status:'ready',stale:false,expired:false,complete:true,blocked:false},
 {status:'ready',stale:true,expired:false,complete:true,blocked:true},
 {status:'ready',stale:false,expired:true,complete:true,blocked:true},
 {status:'confirmed',stale:true,expired:true,complete:true,blocked:true},
 {status:'ready',stale:false,expired:false,complete:false,blocked:true},
])('presentación conserva restricciones de $status, stale=$stale, expired=$expired',({blocked,...state})=>{
 expect(Boolean(confirmationBlocker({...ganttScenarioFixture,scenario:{...ganttScenarioFixture.scenario!,...state}}))).toBe(blocked)
})

test('initial válido sólo es confirmable sin CURRENT',()=>{
 const data={...ganttScenarioFixture,scenario:{...ganttScenarioFixture.scenario!,scenario_kind:'initial'}}
 expect(confirmationBlocker(data)).toMatch(/ya existe un plan vigente/)
 expect(confirmationBlocker({...data,plan_version_id:null,plan_version_number:null})).toBeNull()
})

test('etiqueta humana local distingue histórico, fecha, tipo y origen sin UUID',()=>{
 const option={...ganttFixture.available_scenarios[0],scenario_kind:'initial',status:'confirmed',expired:true,origin_plan_version_number:1}
 const label=scenarioLabel(option,'America/Argentina/Cordoba')
 expect(label).toMatch(/29\/09\/2026/);expect(label).toContain('09:00:00')
 expect(label).toContain('Inicial');expect(label).toContain('Confirmada');expect(label).toContain('Desactualizada')
 expect(label).toContain('ORIGEN DE CURRENT V1');expect(label).not.toContain(option.id)
})
