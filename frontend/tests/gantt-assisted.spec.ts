import { test,expect,type Page } from '@playwright/test'
import { ganttFixture,ganttScenarioFixture } from '../src/test/fixtures'

test.setTimeout(90_000)

const futureOperation={
  ...ganttFixture.operations[0],operational_status:'PENDIENTE',
  executed_minutes:0,actual_segments:[],
}
const current={...ganttFixture,operations:[futureOperation]}
const scenario={...ganttScenarioFixture,operations:[futureOperation],scenario:{
  ...ganttScenarioFixture.scenario!,
  manual_intent:{
    requested_start:'2026-10-20T14:00:00Z',
    proposed_start:'2026-10-20T15:30:00Z',
    proposed_finish:'2026-10-20T19:30:00Z',
    exact_request_satisfied:false,
    explanations:['PHYSICAL_RESOURCE_OCCUPIED'],
  },
}}

async function mockAssistedApi(page:Page){
  let promoted=false
  await page.route('**/api/**',async route=>{
    const request=route.request(),url=new URL(request.url())
    if(url.pathname==='/api/planning/current/gantt'){
      if(url.searchParams.has('scenario_id'))return route.fulfill({json:scenario})
      return route.fulfill({json:promoted?{
        ...current,plan_version_number:7,operations:[{
          ...futureOperation,planned_start:'2026-10-20T15:30:00Z',
          planned_finish:'2026-10-20T19:30:00Z',
        }],available_scenarios:[],
      }:current})
    }
    if(url.pathname.endsWith('/move')&&request.method()==='POST'){
      return route.fulfill({status:201,json:{
        scenario_id:scenario.scenario!.id,
        schedule_solution_id:'14141414-1414-4141-8141-141414141414',
        status:'ready',requested_start:'2026-10-20T14:00:00Z',
        requested_finish:'2026-10-20T18:00:00Z',
        proposed_start:'2026-10-20T15:30:00Z',
        proposed_finish:'2026-10-20T19:30:00Z',
        exact_request_satisfied:false,changed_operations:1,affected_projects:1,
        customer_date_alerts:0,communication_recommended:false,
        explanations:['PHYSICAL_RESOURCE_OCCUPIED'],stale:false,
        idempotent_replay:false,
      }})
    }
    if(url.pathname.endsWith('/resize')&&request.method()==='POST'){
      return route.fulfill({status:201,json:{
        scenario_id:scenario.scenario!.id,
        schedule_solution_id:'14141414-1414-4141-8141-141414141414',
        status:'ready',requested_start:futureOperation.planned_start,
        requested_finish:'2026-09-29T16:00:00Z',
        proposed_start:futureOperation.planned_start,
        proposed_finish:'2026-09-29T16:00:00Z',
        exact_request_satisfied:true,changed_operations:1,affected_projects:1,
        customer_date_alerts:0,communication_recommended:false,
        explanations:['REQUESTED_DURATION_SATISFIED'],stale:false,
        idempotent_replay:false,
      }})
    }
    if(url.pathname.endsWith('/reject'))return route.fulfill({json:{status:'rejected'}})
    if(url.pathname.endsWith('/accept')){promoted=true;return route.fulfill({status:201,json:{status:'promoted'}})}
    return route.abort()
  })
}

async function openAdjustment(page:Page){
  await page.goto('/planning/gantt',{waitUntil:'domcontentloaded'})
  await expect(page.getByText(/Plan vigente V6/)).toBeVisible()
  await page.getByRole('button',{name:'MODO AJUSTE'}).click()
}

test.beforeEach(async({page})=>mockAssistedApi(page))

test('drag crea intención y cancelar no llama mutación',async({page},testInfo)=>{
  test.skip(testInfo.project.name==='smartphone-390','drag no es obligatorio en smartphone')
  let moveCalls=0
  await page.route('**/api/planning/activities/*/move',async route=>{
    moveCalls++;await route.fallback()
  })
  await openAdjustment(page)
  const item=page.locator('.vis-item.gantt-plan').first()
  await item.click()
  const box=await item.boundingBox()
  expect(box).not.toBeNull()
  await page.mouse.move(box!.x+box!.width/2,box!.y+box!.height/2)
  await page.mouse.down()
  await page.mouse.move(box!.x+box!.width/2+80,box!.y+box!.height/2,{steps:8})
  await page.mouse.up()
  await expect(page.getByRole('region',{name:'Proponer cambio'})).toBeVisible()
  await page.getByRole('button',{name:'CANCELAR'}).click()
  await expect(page.getByRole('region',{name:'Proponer cambio'})).toHaveCount(0)
  expect(moveCalls).toBe(0)
})

test('formulario simula alternativa y permite reject conservando CURRENT',async({page})=>{
  await openAdjustment(page)
  const chooser=page.viewportSize()!.width<=700
    ? page.getByRole('region',{name:'Operaciones visibles'}).getByRole('button').first()
    : page.getByRole('button',{name:/Plan vigente, Cocina Pérez, Armado/})
  await chooser.click()
  await page.getByLabel('Fecha y hora solicitada').fill('2026-10-20T11:00')
  await page.getByRole('button',{name:'PROPONER HORARIO'}).click()
  await page.getByRole('button',{name:'SIMULAR CAMBIO'}).click()
  await expect(page.getByText('Primera posición factible')).toBeVisible()
  await expect(page.getByText(/PHYSICAL_RESOURCE_OCCUPIED/)).toBeVisible()
  await page.getByRole('button',{name:'CANCELAR PROPUESTA'}).click()
  await expect(page.getByText(/realidad registrada se mantiene/)).toBeVisible()
  await expect(page.getByText(/Plan vigente V6/)).toBeVisible()
})

test('smartphone dispone de alternativa sin depender de drag',async({page},testInfo)=>{
  test.skip(testInfo.project.name!=='smartphone-390','validación específica smartphone')
  await openAdjustment(page)
  await expect(page.getByRole('region',{name:/Sólo lectura/})).toBeVisible()
  await page.getByRole('region',{name:'Operaciones visibles'}).getByRole('button').first().click()
  await expect(page.getByLabel('Fecha y hora solicitada')).toBeVisible()
  await page.getByLabel('Fecha y hora solicitada').fill('2026-10-20T11:00')
  await page.getByRole('button',{name:'PROPONER HORARIO'}).click()
  await expect(page.getByRole('region',{name:'Proponer cambio'})).toBeVisible()
})

test('move simulado puede aceptarse y refresca CURRENT V7',async({page},testInfo)=>{
  test.skip(testInfo.project.name==='smartphone-390','cubierto por formulario smartphone')
  await openAdjustment(page)
  await page.getByRole('button',{name:/Plan vigente, Cocina Pérez, Armado/}).click()
  await page.getByLabel('Fecha y hora solicitada').fill('2026-10-20T11:00')
  await page.getByRole('button',{name:'PROPONER HORARIO'}).click()
  await page.getByRole('button',{name:'SIMULAR CAMBIO'}).click()
  await expect(page.getByText('Primera posición factible')).toBeVisible()
  await page.getByRole('button',{name:'CONFIRMAR NUEVO PLAN'}).click()
  await expect(page.getByText(/Plan vigente V7/)).toBeVisible()
  await expect(page.getByText(/Nueva planificación confirmada/)).toBeVisible()
})

test('resize futuro se presenta como hipótesis explícita',async({page},testInfo)=>{
  test.skip(testInfo.project.name==='smartphone-390','resize visual fuera de smartphone V1')
  await openAdjustment(page)
  await page.getByRole('button',{name:/Plan vigente, Cocina Pérez, Armado/}).click()
  await page.getByLabel('Duración planificada (minutos)').fill('300')
  await page.getByRole('button',{name:'PROPONER DURACIÓN'}).click()
  await expect(page.getByRole('region',{name:'Proponer cambio'})).toContainText(
    'Estimación planificada hipotética',
  )
  await page.getByRole('button',{name:'SIMULAR CAMBIO'}).click()
  await expect(page.getByText(/posición solicitada es factible/i)).toBeVisible()
})

test('operación en curso deriva a tiempo restante',async({page},testInfo)=>{
  test.skip(testInfo.project.name==='smartphone-390','cubierto en UI operativa desktop')
  await page.route('**/api/planning/current/gantt**',route=>route.fulfill({json:ganttFixture}))
  await openAdjustment(page)
  await page.getByRole('button',{name:/Plan vigente, Cocina Pérez, Armado/}).click()
  await expect(page.getByText(/actualizá el tiempo restante/i)).toBeVisible()
  await expect(page.getByRole('button',{name:'PROPONER DURACIÓN'})).toHaveCount(0)
})
