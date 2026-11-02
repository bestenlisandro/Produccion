import {test,expect} from '@playwright/test'
import {ganttV2Fixture,initialV2Fixture} from '../src/test/ganttV2Fixture'
import {ganttScenarioFixture} from '../src/test/fixtures'

test.beforeEach(async({page})=>{
 await page.route('**/api/**',route=>{
  if(route.request().method()!=='GET')throw new Error('Este flujo de inspección no debe mutar')
  const url=new URL(route.request().url()),group=(url.searchParams.get('group_by')??'project') as 'project'|'person'|'resource'|'center'
  const data=url.searchParams.has('scenario_id')?initialV2Fixture:{...ganttV2Fixture,plan_version_id:null,operations:[],scenario:null}
  const grouped={...data,group_by:group,groups:group==='project'?data.groups:[{id:'project-v2',label:{person:'Gonzalo',resource:'Escuadradora 1',center:'Armado'}[group],kind:group}]}
  return route.fulfill({json:grouped})
 })
})
test('sin CURRENT revisa propuesta, paralelos, detalle y dependencias sin aceptar',async({page},info)=>{
 await page.goto('/planning/gantt')
 await expect(page.getByText(/Elegí una simulación/)).toBeVisible()
 await page.getByLabel('Comparar con').selectOption(ganttScenarioFixture.scenario!.id)
 await expect(page.getByRole('region',{name:'Impacto de simulación'})).toContainText('Completa')
 const mobile=info.project.name==='smartphone-390'
 if(mobile){
  await page.getByRole('region',{name:'Operaciones visibles'}).getByRole('button',{name:/Alacenas \(fixture\) · Armado/}).click()
 }else{
  await expect(page.locator('[data-dependency]')).toHaveCount(0)
  await page.getByRole('button',{name:/Inspeccionar Armado/}).click()
  await expect(page.locator('[data-dependency]')).toHaveCount(3)
 }
 const detail=page.getByRole('dialog',{name:'Detalle de operación'})
 await expect(detail).toContainText('Corte Fondos, Multiple')
 await expect(detail).toContainText('Instalación')
 await expect(detail).toContainText('Banco 1')
 await expect(detail).toContainText('El recurso necesario está ocupado.')
 await expect(detail).toContainText('Divisible')
 await page.keyboard.press('Escape');await expect(detail).toHaveCount(0)
 if(!mobile){
  await page.getByLabel('Dependencias',{exact:true}).selectOption('all');await expect(page.locator('[data-dependency]')).toHaveCount(3)
  await expect(page.locator('[data-dependency="op-0:op-1"]')).toHaveCount(0)
  await page.getByLabel('Dependencias',{exact:true}).selectOption('hidden');await expect(page.locator('[data-dependency]')).toHaveCount(0)
 }
 await expect(page.getByRole('button',{name:'CONFIRMAR NUEVO PLAN'})).toBeEnabled()
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true)
 await page.screenshot({path:info.outputPath('gantt-v2-overview.png'),fullPage:true})
})
test('agrupaciones, plegado, zoom y navegación accesible',async({page},info)=>{
 await page.goto(`/planning/gantt?scenario_id=${ganttScenarioFixture.scenario!.id}`)
 await expect(page.getByRole('heading',{name:'Gantt operativo'})).toBeVisible()
 for(const value of ['person','resource','center','project']){
  await page.getByLabel('Agrupar por').selectOption(value)
  await expect(page.getByLabel('Agrupar por')).toHaveValue(value)
 }
 if(info.project.name!=='smartphone-390'){
  const group=page.getByRole('button',{name:/A685 · Alacenas/})
  await group.focus();await page.keyboard.press('Enter');await expect(group).toHaveAttribute('aria-expanded','false')
  await page.keyboard.press('Enter');await expect(group).toHaveAttribute('aria-expanded','true')
  const stage=page.getByRole('button',{name:'6. Armado'});await stage.click();await expect(stage).toHaveAttribute('aria-expanded','false')
 }
 for(const label of ['Día','Mes','2 semanas','Semana']){await page.getByRole('button',{name:label,exact:true}).click();await expect(page.getByRole('button',{name:label,exact:true})).toHaveAttribute('aria-pressed','true')}
 await page.getByRole('button',{name:'AJUSTAR AL PLAN'}).click()
 await page.getByRole('button',{name:'HOY',exact:true}).click()
})
test('CURRENT y propuesta se distinguen, filtro sin mutación',async({page},info)=>{
 await page.route('**/api/planning/current/gantt**',route=>route.fulfill({json:{...ganttV2Fixture,scenario:{...ganttScenarioFixture.scenario!,operations:ganttV2Fixture.operations.map((o,i)=>({operation_id:o.operation_id,planned_start:o.planned_start,planned_finish:o.planned_finish,difference:i===2?'DELAYED':'UNCHANGED',delta_minutes:i===2?60:0}))}}}))
 await page.goto('/planning/gantt')
 await expect(page.getByRole('region',{name:'Impacto de simulación'})).toContainText('PLAN ACTUAL vs PROPUESTA')
 await page.getByRole('button',{name:'VER CAMBIOS'}).click()
 if(info.project.name==='smartphone-390')await expect(page.getByRole('region',{name:'Operaciones visibles'}).getByRole('button')).toHaveCount(1)
 else await expect(page.getByRole('button',{name:/Inspeccionar/})).toHaveCount(1)
 await page.getByRole('button',{name:'VER PLAN COMPLETO'}).click()
 await page.screenshot({path:info.outputPath('gantt-v2-comparison.png'),fullPage:true})
 if(info.project.name==='desktop-1366'){await page.setViewportSize({width:1280,height:800});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);await page.screenshot({path:info.outputPath('gantt-v2-laptop-1280.png'),fullPage:true})}
})
