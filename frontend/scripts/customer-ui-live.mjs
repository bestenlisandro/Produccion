// Real HTTP/database smoke; no API mocks. Invoked only by the disposable runner.
import assert from 'node:assert/strict'
import { chromium } from 'playwright'
import { createServer } from 'vite'

const api=process.env.CUSTOMER_SMOKE_API
assert.match(api??'',/^http:\/\/127\.0\.0\.1:\d+$/)
const vite=await createServer({server:{host:'127.0.0.1',port:0,strictPort:true,proxy:{'/api':{target:api,changeOrigin:true,rewrite:path=>path.replace(/^\/api/,'')}}}})
let browser
try{
  await vite.listen()
  const origin=`http://127.0.0.1:${vite.httpServer.address().port}`
  browser=await chromium.launch({channel:process.env.PLAYWRIGHT_CHANNEL??'msedge',headless:true})
  const page=await browser.newPage()
  const errors=[];page.on('pageerror',error=>errors.push(error.message))
  await page.goto(origin+'/projects/new')
  await page.getByRole('button',{name:'+ NUEVO CLIENTE'}).waitFor()
  await page.getByLabel('Código del proyecto').fill('A685')
  await page.getByLabel('Nombre / referencia').fill('Referencia E2E descartable')
  const priority=await page.getByLabel('Prioridad del proyecto').inputValue()
  await page.getByLabel('Fecha comprometida').fill('2026-12-24')
  await page.getByLabel('Notas').fill('No perder este borrador')
  await page.getByRole('button',{name:'+ NUEVO CLIENTE'}).click()
  await page.getByLabel('Nombre / razón social').fill('Cliente E2E descartable')
  const responsePromise=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/customers'&&response.request().method()==='POST')
  await page.getByRole('button',{name:'CREAR CLIENTE',exact:true}).click()
  const response=await responsePromise
  assert.equal(response.status(),201)
  const result=await response.json()
  await page.getByRole('dialog').waitFor({state:'detached'})
  assert.equal(await page.getByLabel('Cliente',{exact:true}).inputValue(),result.customer.id)
  for(const [label,value] of [['Código del proyecto','A685'],['Nombre / referencia','Referencia E2E descartable'],['Prioridad del proyecto',priority],['Fecha comprometida','2026-12-24'],['Notas','No perder este borrador']]){
    assert.equal(await page.getByLabel(label).inputValue(),value)
  }
  const request=response.request()
  const headers=await request.allHeaders()
  const retry=await page.request.post(origin+'/api/customers',{data:request.postDataJSON(),headers:Object.fromEntries(['x-dev-organization-id','x-dev-plant-id','x-dev-user-id','idempotency-key'].map(key=>[key,headers[key]]))})
  assert.equal(retry.status(),201)
  const replay=await retry.json()
  assert.equal(replay.customer.id,result.customer.id)
  assert.equal(replay.idempotent_replay,true)
  assert.deepEqual(errors,[])
  console.log('BROWSER_DB_SMOKE: A685 + all fields preserved, customer selected, modal closed, real idempotent retry passed.')
}finally{
  if(browser)await browser.close()
  await vite.close()
}
