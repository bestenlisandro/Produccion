import {test,expect} from '@playwright/test'
import {ganttFixture,ganttScenarioFixture} from '../src/test/fixtures'

for(const preventive of [true,false]){
 test(`simulación vencida ${preventive?'preventiva':'al confirmar'} preserva el vigente`,async({page})=>{
  let accepts=0,simulations=0
  await page.route('**/api/**',async route=>{
   const req=route.request(),url=new URL(req.url())
   if(req.method()==='GET'&&url.pathname==='/api/planning/current/gantt')return route.fulfill({json:url.searchParams.has('scenario_id')?{...ganttScenarioFixture,scenario:{...ganttScenarioFixture.scenario!,expired:preventive}}:ganttFixture})
   if(req.method()==='POST'&&url.pathname.endsWith('/accept')){accepts++;return route.fulfill({status:409,json:{error:{code:'SCENARIO_EXPIRED',message:'Esta simulación quedó desactualizada. Generá una nueva simulación antes de confirmar el plan.'}}})}
   if(req.method()==='POST'){simulations++;return route.abort()}
   return route.abort()
  })
  await page.goto('/planning/gantt')
  await expect(page.getByText(/Plan vigente V6/)).toBeVisible()
  await page.getByLabel('Comparar con').selectOption(ganttScenarioFixture.scenario!.id)
  const confirm=page.getByRole('button',{name:'CONFIRMAR NUEVO PLAN'})
  if(preventive){await expect(page.getByText('SIMULACIÓN DESACTUALIZADA',{exact:true})).toBeVisible();await expect(confirm).toBeDisabled()}
  else{await confirm.click();await expect(page.getByText(/Esta simulación quedó desactualizada porque/)).toBeVisible();expect(accepts).toBe(1)}
  await expect(page.getByText(/Plan vigente V6/)).toBeVisible()
  expect(simulations).toBe(0)
 })
}
