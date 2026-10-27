import { test,expect } from '@playwright/test'
import { ganttFixture } from '../src/test/fixtures'
import { initialGanttFixture,initialScenarioId } from '../src/test/initialScenarioFixture'

test('primera simulación visible y CURRENT sólo tras aceptar explícitamente',async({page})=>{
 let accepted=false,accepts=0
 await page.route('**/api/**',route=>{
  const request=route.request(),url=new URL(request.url())
  if(url.pathname.endsWith('/accept')){accepts++;accepted=true;return route.fulfill({status:201,json:{plan_version_id:ganttFixture.plan_version_id}})}
  if(url.pathname==='/api/planning/current/gantt')return route.fulfill({json:accepted&&!url.searchParams.has('scenario_id')?{...ganttFixture,plan_version_number:1}:initialGanttFixture})
  throw new Error('Unexpected write or request: '+request.url())
 })
 await page.goto(`/planning/gantt?scenario_id=${initialScenarioId}`)
 const detail=page.getByRole('region',{name:'Detalle de simulación inicial'})
 await expect(detail).toBeVisible()
 await expect(detail).toContainText('Operador Uno')
 await expect(detail).toContainText('Banco 1')
 await expect(detail).toContainText('120 min')
 await expect(page.getByText(/Fecha final estimada:/)).toBeVisible()
 expect(accepts).toBe(0);expect(accepted).toBe(false)
 await page.getByRole('button',{name:'CONFIRMAR NUEVO PLAN'}).click()
 await expect(page.getByText(/Plan vigente V1/)).toBeVisible()
 await expect(page.getByRole('region',{name:'Notificaciones'})).toContainText('Nuevo plan confirmado.')
 expect(accepts).toBe(1)
})

test('primera simulación bloqueada muestra motivos sin aceptar',async({page})=>{
 let writes=0
 const data={...initialGanttFixture,scenario:{...initialGanttFixture.scenario!,complete:false},operations:initialGanttFixture.operations.map(o=>({...o,planned_start:null,planned_finish:null,people:[],centers:[],resources:[],blocker_code:'REQUIRED_SKILL_UNAVAILABLE',operational_status:'BLOQUEADO'}))}
 await page.route('**/api/**',route=>{if(route.request().method()!=='GET')writes++;return route.fulfill({json:new URL(route.request().url()).searchParams.has('scenario_id')?data:{...data,operations:[],scenario:null}})})
 await page.goto(`/planning/gantt?scenario_id=${initialScenarioId}`)
 await expect(page.getByText(/Simulación incompleta/)).toBeVisible()
 await expect(page.getByRole('button',{name:'CONFIRMAR NUEVO PLAN'})).toBeDisabled()
 await expect(page.getByRole('region',{name:'Detalle de simulación inicial'})).toContainText('Sin inicio')
 expect(writes).toBe(0)
})
