import { test,expect,type Page } from '@playwright/test'
import { projectFixture,projectOptions } from '../src/test/projectIntakeFixture'
import { readinessFixture } from '../src/test/productionReadinessFixture'

async function setup(page:Page,failFirst=false){
 const calls:{body:any;key:string|undefined}[]=[]
 const ready={...readinessFixture,released:true,eligible:true,state:'released'}
 await page.clock.setFixedTime(new Date('2026-10-26T01:00:00Z'))
 await page.route('**/api/**',async route=>{
  const request=route.request(),path=new URL(request.url()).pathname
  if(path.endsWith('/simulations')){
   calls.push({body:request.postDataJSON(),key:request.headers()['idempotency-key']})
   await new Promise(r=>setTimeout(r,100))
   if(failFirst&&calls.length===1)return route.fulfill({status:500,json:{}})
   return route.fulfill({json:{scenario_id:projectFixture.id,solution_id:projectFixture.id,status:'ready',complete:true,planned_phases:1,blocked_phases:0}})
  }
  if(path==='/api/project-intake/options')return route.fulfill({json:projectOptions})
  if(path.endsWith('/installations'))return route.fulfill({json:{project_id:projectFixture.id,project_code:projectFixture.code,project_name:projectFixture.name,customer_name:projectFixture.customer_name,row_version:1,timezone:ready.timezone,required:false,can_complete:false,completed:false,installations:[]}})
  if(path===`/api/projects/${projectFixture.id}`)return route.fulfill({json:{...projectFixture,production_readiness:ready}})
  throw new Error('Unexpected request '+path)
 })
 await page.goto(`/projects/${projectFixture.id}`)
 await expect(page.getByRole('button',{name:'GENERAR SIMULACIÓN'})).toBeVisible()
 return calls
}

test('día local, doble click y segunda simulación sólo tras nueva intención',async({page})=>{
 const calls=await setup(page)
 const start=page.getByLabel('Inicio del horizonte (fecha local)')
 await expect(start).toHaveValue('2026-10-25')
 await start.fill('2026-10-26')
 await page.getByRole('button',{name:'GENERAR SIMULACIÓN'}).dblclick()
 await expect(page.getByRole('link',{name:'ABRIR PLANIFICACIÓN'})).toBeVisible()
 expect(calls).toHaveLength(1);expect(calls[0].body.horizon_start).toBe('2026-10-26')
 await expect(page.getByRole('button',{name:'GENERAR SIMULACIÓN'})).toBeDisabled()
 await page.getByRole('button',{name:'PREPARAR OTRA SIMULACIÓN'}).click()
 await start.fill('2026-10-27')
 await page.getByRole('button',{name:'GENERAR SIMULACIÓN'}).click()
 await expect(page.getByRole('link',{name:'ABRIR PLANIFICACIÓN'})).toBeVisible()
 expect(calls).toHaveLength(2);expect(calls[1].key).not.toBe(calls[0].key)
 expect(calls[1].body.horizon_start).toBe('2026-10-27')
})

test('retry técnico no cambia key ni fechas y no acepta planes',async({page})=>{
 const calls=await setup(page,true)
 await page.getByRole('button',{name:'GENERAR SIMULACIÓN'}).click()
 await expect(page.getByLabel('Inicio del horizonte (fecha local)')).toBeDisabled()
 await page.getByRole('button',{name:'REINTENTAR MISMA ACCIÓN'}).click()
 await expect(page.getByRole('link',{name:'ABRIR PLANIFICACIÓN'})).toBeVisible()
 expect(calls).toHaveLength(2);expect(calls[1]).toEqual(calls[0])
})
