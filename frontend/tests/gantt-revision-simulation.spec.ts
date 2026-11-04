import {test,expect} from '@playwright/test'
import {revisionSimulationFixture,revisionSimulationId} from '../src/test/ganttRevisionSimulationFixture'

test('URL directa de simulation READY REV5 carga comparación con CURRENT V1 y DAG paralelo',async({page},info)=>{
 let mutations=0
 await page.route('**/api/**',route=>{
  if(route.request().method()!=='GET'){mutations++;return route.abort()}
  const url=new URL(route.request().url())
  if(url.pathname==='/api/planning/current/gantt')return route.fulfill({json:{...revisionSimulationFixture,range_from:url.searchParams.get('from'),range_to:url.searchParams.get('to')}})
  return route.abort()
 })
 await page.goto(`/planning/gantt?scenario_id=${revisionSimulationId}`)
 await expect(page.getByRole('heading',{name:'Gantt operativo'})).toBeVisible()
 await expect(page.getByText('No pudimos cargar la información.')).toHaveCount(0)
 await expect(page.getByText(/Plan vigente V1/)).toBeVisible()
 await expect(page.getByLabel('Comparar con')).toHaveValue(revisionSimulationId)
 await expect(page.getByRole('option',{name:/Simulación · Vigente \/ revisable/})).toHaveCount(1)
 const impact=page.getByRole('region',{name:'Impacto de simulación'})
 await expect(impact).toContainText('Corte Fondos 3 mm')
 await expect(impact).toContainText('Procesado Múltiple 18 mm')
 if(info.project.name!=='smartphone-390'){
  await expect(page.locator('.gantt-scenario')).toHaveCount(4)
  await page.getByRole('button',{name:'AJUSTAR AL PLAN'}).click()
  await page.getByLabel('Dependencias',{exact:true}).selectOption('all')
  await expect(page.locator('[data-dependency="op-0:op-2"]')).toHaveCount(1)
  await expect(page.locator('[data-dependency="op-1:op-2"]')).toHaveCount(1)
  await expect(page.locator('[data-dependency="op-0:op-1"]')).toHaveCount(0)
 }
 expect(mutations).toBe(0)
})
