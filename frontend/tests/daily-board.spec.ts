import { test,expect } from '@playwright/test'

const operation={operation_id:'11111111-1111-4111-8111-111111111111',project_id:'22222222-2222-4222-8222-222222222222',project_code:'P-1',project_name:'Cocina Pérez',lot_code:'L-1',lot_name:'Muebles bajos',operation_code:'ARM',operation_name:'Armado',phase_name:'Trabajo',planned_start:'2026-09-21T08:00:00Z',planned_finish:'2026-09-21T12:00:00Z',people:[],work_center:'Armado',physical_resource:'Banco 1',priority:'Alta',priority_rank:1,operational_status:'EN_CURSO',progress_percent:70,executed_minutes:420,remaining_minutes:180,blocker_code:null}
const scenarioId='66666666-6666-4666-8666-666666666666'

test.beforeEach(async({page})=>{
  let reconciles=false, remaining=180, promoted=false
  await page.route('**/api/**',async route=>{
    const request=route.request(), url=new URL(request.url()), method=request.method()
    if(url.pathname==='/api/planning/current/day'&&method==='GET') return route.fulfill({json:{date:'2026-09-21',operations:[{...operation,operation_name:promoted?'Armado reprogramado':operation.operation_name,remaining_minutes:remaining}]}})
    if(url.pathname===`/api/operations/${operation.operation_id}`&&method==='GET') return route.fulfill({json:{...operation,operation_name:promoted?'Armado reprogramado':operation.operation_name,remaining_minutes:remaining,phase_id:'55555555-5555-4555-8555-555555555555',original_estimate_minutes:600,plan_requires_reconciliation:reconciles,next_operation_name:null}})
    if(url.pathname.endsWith('/remaining-estimate')&&method==='POST'){reconciles=true;remaining=240;return route.fulfill({json:{revision_id:crypto.randomUUID(),revision_number:2,original_minutes:600,executed_minutes:420,remaining_minutes:remaining,updated_total_minutes:660,planning_state_revision_id:crypto.randomUUID(),planning_state_revision_number:2,effective_event_id:crypto.randomUUID(),current_plan_version_id:crypto.randomUUID()}})}
    if(url.pathname.endsWith('/replan')&&method==='POST') return route.fulfill({status:201,json:{scenario_id:scenarioId,status:'ready',complete:true,changed_operations:3,affected_projects:2,customer_date_alerts:0,communication_recommended:false,idempotent_replay:false}})
    if(url.pathname===`/api/scenarios/${scenarioId}`&&method==='GET') return route.fulfill({json:{id:scenarioId,status:'ready',base_plan_version_id:crypto.randomUUID(),base_state_revision_id:crypto.randomUUID(),base_product_definition_revision_id:crypto.randomUUID(),stale:false,rejected:false,promoted:false,promoted_plan_version_id:null,row_version:2,promotion_lock_version:1,changed_operations:3,affected_projects:2,customer_date_alerts:0,communication_recommended:false,impacts:[]}})
    if(url.pathname.endsWith('/reject')&&method==='POST') return route.fulfill({json:{scenario_id:scenarioId,status:'rejected',row_version:3,idempotent_replay:false}})
    if(url.pathname.endsWith('/accept')&&method==='POST'){promoted=true;reconciles=false;return route.fulfill({status:201,json:{ok:true}})}
    return route.abort()
  })
})

async function openOperation(page: import('@playwright/test').Page){await page.goto('/',{waitUntil:'domcontentloaded'});await expect(page.getByRole('table').getByText('Cocina Pérez')).toBeVisible();await page.getByRole('link',{name:'Armado'}).click();await expect(page.getByRole('heading',{name:'Armado'})).toBeVisible()}
async function updateAndSimulate(page: import('@playwright/test').Page){await openOperation(page);await page.getByText('+1 h').click();await page.getByText('GUARDAR ESTIMACIÓN').click();await expect(page.getByText(/planificación necesita revisión/i)).toBeVisible();await page.getByText('SIMULAR REPROGRAMACIÓN').click();await expect(page.getByText('Reprogramación propuesta')).toBeVisible()}

test('flujo A: abre tablero y detalle',async({page})=>{await openOperation(page)})
test('flujo B: actualiza, simula y cancela conservando realidad',async({page})=>{await updateAndSimulate(page);await page.getByText('CANCELAR PROPUESTA').click();await expect(page.getByText(/estimación real actualizada se mantiene/)).toBeVisible();await expect(page.getByText('4 h 0 min')).toBeVisible()})
test('flujo C: actualiza, simula, acepta y refresca el plan vigente',async({page})=>{let boardReads=0;page.on('request',request=>{if(new URL(request.url()).pathname==='/api/planning/current/day')boardReads++});await updateAndSimulate(page);await page.getByText('CONFIRMAR NUEVO PLAN').click();await expect(page.getByText('Nueva planificación confirmada.')).toBeVisible();await expect.poll(()=>boardReads).toBeGreaterThan(1);await page.getByRole('link',{name:/Volver al tablero/}).click();await expect(page.getByRole('link',{name:'Armado reprogramado'})).toBeVisible()})
test('stale: un 409 explica el cambio y permite volver a simular',async({page})=>{await page.route(`**/api/scenarios/${scenarioId}/accept`,route=>route.fulfill({status:409,json:{error:{code:'SCHEDULING_BASE_STALE',message:'stale'}}}));await updateAndSimulate(page);await page.getByText('CONFIRMAR NUEVO PLAN').click();await expect(page.getByText(/situación de producción cambió/)).toBeVisible();await expect(page.getByText('VOLVER A SIMULAR')).toBeVisible()})
