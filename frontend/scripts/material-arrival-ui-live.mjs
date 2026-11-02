// Requires the guarded disposable PostgreSQL pytest runner. No mocked APIs.
import assert from 'node:assert/strict'
import {mkdir} from 'node:fs/promises'
import {chromium} from 'playwright'
import {createServer} from 'vite'

const api=process.env.MATERIAL_ROUTES_API
assert.match(api??'',/^http:\/\/127\.0\.0\.1:\d+$/)
const projects=JSON.parse(process.env.MATERIAL_ROUTES_PROJECTS??'[]')
assert.equal(projects.length,8)
const vite=await createServer({server:{host:'127.0.0.1',port:0,strictPort:true,proxy:{'/api':{target:api,changeOrigin:true,rewrite:path=>path.replace(/^\/api/,'')}}}})
let browser
await mkdir('../test-results/material-arrival',{recursive:true})
try{
 await vite.listen()
 const origin=`http://127.0.0.1:${vite.httpServer.address().port}`
 browser=await chromium.launch({channel:process.env.PLAYWRIGHT_CHANNEL??'msedge',headless:true})
 for(const project of projects){
  const page=await browser.newPage({viewport:{width:project.width,height:900}})
  const errors=[];page.on('pageerror',e=>errors.push(e.message));page.on('dialog',dialog=>dialog.accept())
  await page.goto(`${origin}/projects/${project.id}/product-definition`)
  await page.getByRole('button',{name:'AGREGAR LOTE',exact:true}).click()
  await page.getByRole('button',{name:'CONFIGURAR LLEGADA DEL MATERIAL'}).click()
  const selector=page.getByLabel('Cómo llega el material',{exact:true})
  await selector.selectOption(`MATERIAL_ROUTE_${project.route}`)
  const optional=page.getByLabel(`Ranurado · Melamina ${project.route===3?'18':'15'} mm · según proyecto`,{exact:true})
  await optional.check()
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),true)
  await page.screenshot({path:`../test-results/material-arrival/config-${project.width}-${project.route}.png`})
  await page.getByRole('button',{name:'REGENERAR DESDE RUTA'}).click()
  await page.locator('input[value="Armado"]').waitFor()
  if(project.route===3){
   assert.equal(await page.locator('input[value="Ranurado · 18 mm"]').count(),1)
   await page.getByRole('button',{name:'CONFIGURAR LLEGADA DEL MATERIAL'}).click()
   await page.getByLabel('Ranurado · Melamina 18 mm · según proyecto',{exact:true}).uncheck()
   await page.getByRole('button',{name:'REGENERAR DESDE RUTA'}).click()
   await page.locator('input[value="Ranurado · 18 mm"]').waitFor({state:'detached'})
  }
  const graph=await page.getByLabel('Nombre de operación',{exact:true}).evaluateAll(inputs=>inputs.map(input=>({name:input.value,predecessors:[...input.closest('details').querySelector('select[multiple]').selectedOptions].map(o=>o.textContent)})))
  const operation=name=>{const op=graph.find(o=>o.name===name);assert.ok(op,name);return op}
  assert.deepEqual(operation('Pegado de cantos · 15 mm').predecessors,['Corte · 15 mm'])
  assert.deepEqual(operation('Múltiple · 15 mm').predecessors,['Pegado de cantos · 15 mm'])
  assert.deepEqual(operation('Corte · Fondo 3 mm').predecessors,[])
  assert.deepEqual(operation('Corte · Fondo 5,5 mm').predecessors,[])
  const assembly=operation('Armado').predecessors
  assert.ok(assembly.includes('Corte · Fondo 3 mm')&&assembly.includes('Corte · Fondo 5,5 mm'))
  assert.ok(!assembly.includes('Pegado de cantos · 15 mm')&&!assembly.includes('Corte · 15 mm'))
  if(project.route===5){
   assert.deepEqual(operation('Múltiple · 18 mm').predecessors,[])
   assert.deepEqual(operation('Ranurado · 15 mm').predecessors,['Pegado de cantos · 15 mm'])
   assert.ok(!graph.some(o=>o.name==='Corte · 18 mm'||o.name==='Pegado de cantos · 12 mm'))
  }
  for(const button of await page.getByRole('button',{name:'AGREGAR FASE',exact:true}).all())await button.click()
  for(const input of await page.getByLabel('Duración estimada (minutos)',{exact:true}).all())await input.fill('15')
  const saved=page.waitForResponse(r=>r.request().method()==='PUT'&&r.url().endsWith(`/projects/${project.id}/product-definition`))
  await page.getByRole('button',{name:'GUARDAR BORRADOR',exact:true}).click()
  const savedResponse=await saved;assert.equal(savedResponse.status(),200)
  assert.equal((await savedResponse.json()).lots[0].material_arrival.route_code,`MATERIAL_ROUTE_${project.route}`)
  const frozen=page.waitForResponse(r=>r.url().endsWith('/product-definition/freeze'))
  await page.getByRole('button',{name:'CONGELAR DEFINICIÓN',exact:true}).click()
  const frozenResponse=await frozen;assert.equal(frozenResponse.status(),200)
  await page.getByText('CONGELADA · Sólo lectura',{exact:true}).waitFor()
  assert.equal(await page.getByLabel('Cómo llega el material',{exact:true}).count(),0)
  assert.equal(await page.getByRole('button',{name:'REGENERAR DESDE RUTA'}).count(),0)
  const denied=await page.request.put(`${api}/projects/${project.id}/product-definition`,{headers:{'x-dev-organization-id':process.env.VITE_DEV_ORGANIZATION_ID,'x-dev-plant-id':process.env.VITE_DEV_PLANT_ID,'x-dev-user-id':process.env.VITE_DEV_USER_ID,'idempotency-key':crypto.randomUUID()},data:{expected_row_version:(await frozenResponse.json()).row_version,lots:[]}})
  assert.equal(denied.status(),409)
  assert.deepEqual(errors,[])
  console.log(`MATERIAL_ROUTES_BROWSER_DB: ${project.width}px / Caso ${project.route} passed`)
  await page.close()
 }
}finally{
 if(browser)await browser.close()
 await vite.close()
}
