import {test,expect} from '@playwright/test'
import {ganttFixture,ganttScenarioFixture} from '../src/test/fixtures'

test('CURRENT V1 compara históricos initial y reconoce su origen sin promover',async({page})=>{
 const source={...ganttFixture.available_scenarios[0],scenario_kind:'initial',status:'confirmed',stale:true,expired:true,created_at:'2026-10-28T17:55:00Z',origin_plan_version_number:1}
 const old={...source,id:'old-initial',status:'stale',origin_plan_version_number:null,created_at:'2026-10-27T18:08:00Z'}
 const replan={...source,id:'future-replan',scenario_kind:'replan',status:'ready',stale:false,expired:false,origin_plan_version_number:null,created_at:'2026-10-29T18:08:00Z'}
 const current={...ganttFixture,plan_version_number:1,available_scenarios:[old,source,replan]}
 let mutations=0
 await page.route('**/api/**',async route=>{
  const req=route.request(),url=new URL(req.url())
  if(req.method()!=='GET'){mutations++;return route.abort()}
  if(url.pathname==='/api/planning/current/gantt'){
   const id=url.searchParams.get('scenario_id'),option=[source,old,replan].find(o=>o.id===id)
   return route.fulfill({json:option?{...current,scenario:{...ganttScenarioFixture.scenario!,id:option.id,status:option.status,stale:option.stale,expired:option.expired,scenario_kind:option.scenario_kind,origin_plan_version_number:option.origin_plan_version_number}}:current})
  }
  return route.abort()
 })
 await page.goto('/planning/gantt')
 await expect(page.getByText(/Plan vigente V1/)).toBeVisible()
 const select=page.getByLabel('Comparar con')
 await expect(select.locator('option')).toHaveCount(4)
 expect(await select.locator('option').allTextContents()).toEqual([
  'Ninguno',expect.stringContaining('Replan · Vigente / revisable'),
  expect.stringContaining('ORIGEN DE CURRENT V1'),expect.stringContaining('Inicial · Desactualizada · Histórica'),
 ])
 await select.selectOption(old.id)
 await expect(page.getByText('SIMULACIÓN DESACTUALIZADA',{exact:true})).toBeVisible()
 await expect(page.getByText(/CURRENT V1 vs SIMULACIÓN SELECCIONADA/)).toBeVisible()
 const confirm=page.getByRole('button',{name:'CONFIRMAR NUEVO PLAN'})
 await expect(confirm).toBeVisible();await expect(confirm).toBeDisabled()
 await expect(page.locator('#scenario-confirmation-blocker')).toContainText('Generá una nueva simulación')
 await expect(page.getByText(/Plan vigente V1/)).toBeVisible()
 if(!test.info().project.name.includes('smartphone')){
  await expect(page.locator('.gantt-plan').first()).toBeVisible()
  await expect(page.locator('.gantt-scenario').first()).toBeVisible()
 }
 await select.selectOption(source.id)
 await expect(page.getByText('ORIGEN DE CURRENT V1 · CONFIRMADA',{exact:true})).toBeVisible()
 await expect(confirm).toBeDisabled()
 await expect(page.locator('#scenario-confirmation-blocker')).toContainText('ya fue confirmada')
 await select.selectOption(replan.id)
 await expect(confirm).toBeEnabled()
 await expect(page.getByText(/Plan vigente V1/)).toBeVisible()
 expect(mutations).toBe(0)
})
