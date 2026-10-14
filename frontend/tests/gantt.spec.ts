import { test,expect,type Page } from '@playwright/test'
import { ganttFixture,ganttScenarioFixture } from '../src/test/fixtures'

test.beforeEach(async({page},testInfo)=>{
  test.skip(testInfo.project.name==='smartphone-390','Gantt desktop/tablet scope')
  let promoted=false
  await page.route('**/api/**',async route=>{
    const request=route.request(),url=new URL(request.url())
    if(url.pathname==='/api/planning/current/gantt'&&request.method()==='GET'){
      const selected=url.searchParams.has('scenario_id')
      const grouping=(url.searchParams.get('group_by')??'center') as 'center'|'resource'|'person'|'project'
      const label={center:'Armado · capacidad 3',resource:'Banco 1',person:'Operador Uno',project:'Cocina Pérez'}[grouping]
      const source=selected?ganttScenarioFixture:ganttFixture
      return route.fulfill({json:{...source,plan_version_number:promoted?7:6,group_by:grouping,groups:[{id:'center-1',label,kind:grouping,capacity:grouping==='center'?3:null}]}})
    }
    if(url.pathname.endsWith('/accept')&&request.method()==='POST'){promoted=true;return route.fulfill({status:201,json:{status:'promoted'}})}
    if(url.pathname.endsWith('/reject')&&request.method()==='POST')return route.fulfill({json:{status:'rejected'}})
    return route.abort()
  })
})

async function openGantt(page:Page){
  await page.goto('/planning/gantt',{waitUntil:'domcontentloaded'})
  await expect(page.getByRole('heading',{name:'Gantt operativo'})).toBeVisible()
  await expect(page.getByText(/Plan vigente V6/)).toBeVisible()
  await expect(page.getByRole('region',{name:/America\/Argentina\/Buenos_Aires/})).toBeVisible()
}

test('flujo A: abre Gantt semanal y detalle operativo',async({page})=>{
  await openGantt(page)
  await expect(page.getByRole('button',{name:'Semana',exact:true})).toHaveAttribute('aria-pressed','true')
  await page.getByRole('button',{name:/Plan vigente, Cocina Pérez, Armado/}).click()
  await expect(page.getByRole('dialog',{name:'Detalle de operación'})).toContainText('Operador Uno')
})

test('flujo B: cambia entre las cuatro agrupaciones',async({page})=>{
  await openGantt(page)
  for(const [value,label] of [['center','Armado'],['resource','Banco 1'],['person','Operador Uno'],['project','Cocina Pérez']] as const){
    await page.getByLabel('Agrupar por').selectOption(value)
    await expect(page.locator('.vis-label').filter({hasText:label}).first()).toBeVisible()
  }
})

test('flujo C: compara plan vigente con simulación',async({page})=>{
  await openGantt(page);await page.getByLabel('Comparar con').selectOption(ganttScenarioFixture.scenario!.id)
  await expect(page.getByText('Retrasada · 60 min')).toBeVisible()
  await expect(page.locator('.difference-delayed').first()).toBeVisible()
})

test('flujo D: acepta y refresca el nuevo plan vigente',async({page})=>{
  await openGantt(page);await page.getByLabel('Comparar con').selectOption(ganttScenarioFixture.scenario!.id)
  await page.getByRole('button',{name:'CONFIRMAR NUEVO PLAN'}).click()
  await expect(page.getByText(/Plan vigente V7/)).toBeVisible()
  await expect(page.getByText(/Nueva planificación confirmada/)).toBeVisible()
})

test('flujo E: escenario stale no permite confirmar',async({page})=>{
  const stale={...ganttScenarioFixture,scenario:{...ganttScenarioFixture.scenario!,stale:true}}
  await page.route('**/api/planning/current/gantt**',route=>route.fulfill({json:stale}))
  await page.goto('/planning/gantt',{waitUntil:'domcontentloaded'})
  await expect(page.getByText('SIMULACIÓN OBSOLETA')).toBeVisible()
  await expect(page.getByRole('button',{name:'CONFIRMAR NUEVO PLAN'})).toHaveCount(0)
})

test('performance: render inicial de 50 proyectos y 250 operaciones',async({page})=>{
  const groups=Array.from({length:50},(_,index)=>({
    id:`00000000-0000-4000-8000-${String(index).padStart(12,'0')}`,
    label:`Proyecto ${index+1}`,kind:'project' as const,
  }))
  const operations=Array.from({length:250},(_,index)=>{
    const group=groups[Math.floor(index/5)]
    return {...ganttFixture.operations[0],
      operation_id:`10000000-0000-4000-8000-${String(index).padStart(12,'0')}`,
      project_id:group.id,project_name:group.label,operation_name:`Operación ${index+1}`,
      group_ids:[group.id],actual_segments:[],
    }
  })
  const scenarioOperations=operations.map((item,index)=>({
    operation_id:item.operation_id,
    planned_start:'2026-09-29T12:00:00Z',
    planned_finish:'2026-09-29T16:00:00Z',
    difference:index%2===0?'DELAYED':'UNCHANGED',
    delta_minutes:index%2===0?60:0,
  }))
  await page.route('**/api/planning/current/gantt**',route=>{
    const selected=new URL(route.request().url()).searchParams.has('scenario_id')
    return route.fulfill({json:{
      ...ganttFixture,group_by:'project',groups,operations,occupations:[],
      scenario:selected?{
        ...ganttScenarioFixture.scenario!,changed_operations:250,
        affected_projects:50,operations:scenarioOperations,
      }:null,
    }})
  })
  const started=Date.now();await page.goto('/planning/gantt',{waitUntil:'domcontentloaded'})
  await expect(page.locator('.vis-item.gantt-plan').first()).toBeAttached()
  await expect(page.locator('section[aria-label="Operaciones visibles"] button')).toHaveCount(250)
  const elapsed=Date.now()-started
  console.log(`GANTT_RENDER_BENCHMARK 50/250=${elapsed}ms`)
  expect(elapsed).toBeLessThan(5000)
  const overlayStarted=Date.now()
  await page.getByLabel('Comparar con').selectOption(ganttScenarioFixture.scenario!.id)
  await expect(page.locator('.vis-item.gantt-scenario').first()).toBeAttached()
  await expect(page.getByText('Operaciones afectadas').locator('..')).toContainText('250')
  const overlayElapsed=Date.now()-overlayStarted
  console.log(`GANTT_OVERLAY_BENCHMARK 50/250=${overlayElapsed}ms`)
  expect(overlayElapsed).toBeLessThan(5000)
})
